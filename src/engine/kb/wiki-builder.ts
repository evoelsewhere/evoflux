import { nanoid } from 'nanoid'
import { listDocuments, listChunksByKB, type KBDocumentRow, type KBChunkRow } from '../db/kb-repo'
import {
  insertEntity, getEntityByName, mergeEntityChunks, linkEntityChunks,
  insertRelationship, insertPage, createBuildProgress, updateBuildProgress,
  getLinkedChunkIds, deleteWikiByKB, getWikiStats,
  type WikiEntity
} from '../db/wiki-repo'
import { embed } from '../memory/embedding'

export interface WikiBuilderOptions {
  providerId: string
  model: string
}

export interface WikiProgress {
  type: 'start' | 'document' | 'merge' | 'page' | 'complete' | 'error'
  current?: number
  total?: number
  entities?: number
  relationships?: number
  error?: string
}

const PARALLEL_WORKERS = 3

type ExtractedEntity = { name: string; type: string; description: string }
type ExtractedRelationship = { source: string; target: string; keywords: string; description: string }

// ==================== Prompts (GraphRAG-inspired) ====================

const ENTITY_TYPES = 'Person, Organization, Location, Event, Concept, Method, API, Class, Function, Config, Tool, Pattern, Technology, File, Module'

const EXTRACTION_PROMPT = `---Role---
You are a Knowledge Graph Specialist responsible for extracting entities and relationships from documents.

---Goal---
Given a text document, identify all significant entities and their relationships.

---Entity Types---
${ENTITY_TYPES}

---Instructions---
1. Entity Extraction:
   - entity_name: Title Case (capitalize first letter of each significant word)
   - entity_type: One of the types listed above
   - entity_description: Concise yet comprehensive description based ONLY on the text
   - Only extract specific, meaningful entities (not generic words)

2. Relationship Extraction:
   - source_entity / target_entity: Use exact entity names from step 1
   - relationship_keywords: High-level keywords separated by comma
   - relationship_description: Concise explanation of how they relate

3. Rules:
   - Max 30 entities, 50 relationships per extraction
   - Entity names must be consistent (Title Case)
   - Descriptions: objective, third-person, factual
   - Only extract relationships between entities you identified
   - Include code-specific entities (functions, classes, APIs, configs)

4. Output Format: Valid JSON only, no markdown

---Output Format---
{
  "entities": [
    {"name": "Entity Name", "type": "Concept", "description": "Description of the entity"}
  ],
  "relationships": [
    {"source": "Entity A", "target": "Entity B", "keywords": "uses, depends_on", "description": "How they relate"}
  ]
}

---Input Text---
{text}
---Output---`

const MERGE_PROMPT = `---Role---
You are a Knowledge Graph data curator responsible for merging entity descriptions.

---Goal---
Synthesize multiple descriptions of the same entity into one comprehensive, accurate summary.

---Instructions---
1. Integrate ALL key information from every description
2. Written from objective, third-person perspective
3. Mention the full entity name at the beginning
4. Resolve contradictions by preferring more specific/detailed descriptions
5. Keep the merged description concise (max 100 words)

---Entity---
Name: {entity_name}
Type: {entity_type}

---Descriptions to Merge---
{descriptions}

---Output---
Write ONLY the merged description, no formatting or labels.`

const OVERVIEW_PROMPT = `---Role---
You are a technical writer creating a knowledge base wiki overview.

---Goal---
Write a comprehensive overview page based on extracted entities and relationships.

---Data---
Knowledge Base: {kb_name}

Documents ({doc_count}):
{doc_summaries}

Entities ({entity_count}):
{entity_list}

Relationships ({rel_count}):
{rel_list}

---Instructions---
Write a wiki overview page in markdown with these sections:

# Overview
[2-3 paragraph executive summary of what this knowledge base covers]

## Key Concepts
[Group the most important entities by type, describe each briefly]

## Architecture & Structure
[Describe how the main components relate to each other]

## Quick Reference
[Table: Name | Type | Description — for top 20 entities]

## Key Relationships
[Describe the most important connections between entities]

Use proper markdown. Be factual and concise. Do not fabricate information.`

const ENTITY_PAGE_PROMPT = `---Role---
You are a technical writer creating a wiki page for a specific entity.

---Goal---
Write a detailed wiki page based on the entity data and source content.

---Entity---
Name: {name}
Type: {type}
Description: {description}

---Relationships---
{relationships}

---Source Documents---
{source_docs}

---Source Content (excerpts)---
{source_content}

---Instructions---
Write a wiki page in markdown:

# {name}
[Comprehensive description - what it is, why it matters]

## Details
[Key facts, parameters, configurations, usage]

## Related Topics
[Links to related entities with brief descriptions]

## References
[Source document names]

Use proper markdown. Be thorough and accurate. Include code examples if relevant.`

// ==================== JSON Parser ====================

function parseJSON(text: string): { entities?: ExtractedEntity[]; relationships?: ExtractedRelationship[] } | null {
  try {
    const match = text.match(/\{[\s\S]*\}/)
    const raw = match ? JSON.parse(match[0]) : JSON.parse(text)
    return {
      entities: Array.isArray(raw.entities) ? raw.entities : [],
      relationships: Array.isArray(raw.relationships) ? raw.relationships : []
    }
  } catch { return null }
}

// ==================== Main Builder ====================

export async function buildWiki(
  kbId: string,
  options: WikiBuilderOptions,
  aiChat: (messages: Array<{ role: string; content: string }>, opts?: { model?: string; provider?: string }) => Promise<string>,
  onProgress?: (progress: WikiProgress) => void
): Promise<{ entities: number; relationships: number; pages: number }> {

  deleteWikiByKB(kbId)

  const documents = listDocuments(kbId)
  if (documents.length === 0) {
    onProgress?.({ type: 'complete', entities: 0, relationships: 0 })
    return { entities: 0, relationships: 0, pages: 0 }
  }

  const allChunks = listChunksByKB(kbId)
  const chunkMap = new Map<string, KBChunkRow[]>()
  for (const chunk of allChunks) {
    if (!chunkMap.has(chunk.doc_id)) chunkMap.set(chunk.doc_id, [])
    chunkMap.get(chunk.doc_id)!.push(chunk)
  }

  const progressId = createBuildProgress(kbId, documents.length)
  onProgress?.({ type: 'start', total: documents.length })

  const entityMap = new Map<string, { entityId: string; name: string; type: string; description: string; chunkIds: string[] }>()
  const allRelationships: Array<{ source: string; target: string; keywords: string; description: string; chunkIds: string[] }> = []
  const documentSummaries: Array<{ name: string; summary: string }> = []
  let failedDocs = 0

  // ==================== Phase 1: Extract entities per document ====================

  async function processDocument(docIdx: number): Promise<void> {
    const doc = documents[docIdx]
    const docChunks = chunkMap.get(doc.id) || []
    if (docChunks.length === 0) return

    const content = docChunks.map(c => c.content).join('\n\n').substring(0, 24000)
    const chunkIds = docChunks.map(c => c.id)

    try {
      const prompt = EXTRACTION_PROMPT.replace('{text}', content)
      const response = await aiChat([
        { role: 'system', content: 'You are a knowledge graph extraction engine. Output valid JSON only.' },
        { role: 'user', content: prompt }
      ], { model: options.model, provider: options.providerId })

      const parsed = parseJSON(response)
      if (!parsed) return

      const docSummary = content.substring(0, 200).replace(/\n/g, ' ')
      documentSummaries.push({ name: doc.name, summary: docSummary })

      for (const entity of (parsed.entities || [])) {
        if (!entity.name || !entity.type) continue
        const normalizedName = entity.name.trim()

        const existing = entityMap.get(normalizedName.toLowerCase())
        if (existing) {
          existing.chunkIds = [...new Set([...existing.chunkIds, ...chunkIds])]
          const dbEntity = getEntityByName(kbId, normalizedName)
          if (dbEntity) mergeEntityChunks(dbEntity.id, chunkIds)
        } else {
          const entityId = `ent-${nanoid(10)}`
          let embBuf: Buffer | null = null
          try {
            const emb = await embed(`${normalizedName}: ${entity.description || ''}`, 'passage')
            embBuf = Buffer.from(emb.buffer)
          } catch { /* skip embedding */ }

          insertEntity({
            id: entityId, kb_id: kbId, name: normalizedName, type: entity.type,
            summary: entity.description || '', description: entity.description || '',
            chunk_ids: JSON.stringify(chunkIds), embedding: embBuf,
            metadata_json: JSON.stringify({ importance: 0.5 })
          })
          linkEntityChunks(entityId, chunkIds)
          entityMap.set(normalizedName.toLowerCase(), {
            entityId, name: normalizedName, type: entity.type,
            description: entity.description || '', chunkIds
          })
        }
      }

      for (const rel of (parsed.relationships || [])) {
        const srcEntity = entityMap.get(rel.source?.trim().toLowerCase())
        const tgtEntity = entityMap.get(rel.target?.trim().toLowerCase())
        if (srcEntity && tgtEntity) {
          allRelationships.push({
            source: srcEntity.entityId, target: tgtEntity.entityId,
            keywords: rel.keywords || '', description: rel.description || '',
            chunkIds
          })
        }
      }

      updateBuildProgress(progressId, {
        completed_batches: docIdx + 1,
        total_entities: entityMap.size,
        total_relationships: allRelationships.length
      })

      onProgress?.({ type: 'document', current: docIdx + 1, total: documents.length, entities: entityMap.size, relationships: allRelationships.length })
    } catch (error) {
      failedDocs++
      onProgress?.({ type: 'error', current: docIdx + 1, total: documents.length, error: error instanceof Error ? error.message : String(error) })
    }
  }

  for (let i = 0; i < documents.length; i += PARALLEL_WORKERS) {
    const indices = []
    for (let j = i; j < Math.min(i + PARALLEL_WORKERS, documents.length); j++) indices.push(j)
    await Promise.all(indices.map(idx => processDocument(idx)))
  }

  // ==================== Phase 2: Deduplicate relationships ====================

  onProgress?.({ type: 'merge', entities: entityMap.size, relationships: allRelationships.length })

  const uniqueRelationships = dedupRelationships(allRelationships)
  for (const rel of uniqueRelationships) {
    insertRelationship({
      id: `rel-${nanoid(10)}`, kb_id: kbId,
      source_entity_id: rel.source, target_entity_id: rel.target,
      type: rel.keywords || 'related_to', label: rel.description,
      weight: 0.8, chunk_ids: JSON.stringify(rel.chunkIds), metadata_json: null
    })
  }

  // ==================== Phase 3: Generate wiki pages ====================

  onProgress?.({ type: 'page', entities: entityMap.size, relationships: uniqueRelationships.length })

  const entitiesList = Array.from(entityMap.values())
  const topEntities = entitiesList.sort((a, b) => (b.chunkIds?.length || 0) - (a.chunkIds?.length || 0))

  // Overview page
  try {
    const overviewPrompt = OVERVIEW_PROMPT
      .replace('{kb_name}', documents[0]?.path?.split('/').slice(0, -1).join('/') || 'Knowledge Base')
      .replace('{doc_count}', String(documents.length))
      .replace('{doc_summaries}', documentSummaries.slice(0, 30).map(s => `- ${s.name}: ${s.summary}`).join('\n'))
      .replace('{entity_count}', String(entitiesList.length))
      .replace('{entity_list}', topEntities.slice(0, 50).map(e => `- **${e.name}** (${e.type}): ${e.description}`).join('\n'))
      .replace('{rel_count}', String(uniqueRelationships.length))
      .replace('{rel_list}', uniqueRelationships.slice(0, 30).map(r => {
        const src = entityMap.get(r.source)?.name || r.source
        const tgt = entityMap.get(r.target)?.name || r.target
        return `- ${src} → ${tgt} (${r.keywords}): ${r.description}`
      }).join('\n'))

    const overviewResp = await aiChat([
      { role: 'system', content: 'You are a technical writer. Write clear, structured wiki pages in markdown.' },
      { role: 'user', content: overviewPrompt }
    ], { model: options.model, provider: options.providerId })

    insertPage({
      id: `pg-${nanoid(10)}`, kb_id: kbId, entity_id: null,
      title: 'Overview', content: overviewResp, type: 'overview', metadata_json: null
    })
  } catch { /* overview is optional */ }

  // Entity pages (top 15 most connected)
  const entityConnectivity = new Map<string, number>()
  for (const rel of uniqueRelationships) {
    entityConnectivity.set(rel.source, (entityConnectivity.get(rel.source) || 0) + 1)
    entityConnectivity.set(rel.target, (entityConnectivity.get(rel.target) || 0) + 1)
  }

  const mostConnected = topEntities
    .sort((a, b) => (entityConnectivity.get(b.entityId) || 0) - (entityConnectivity.get(a.entityId) || 0))
    .slice(0, 15)

  for (const entity of mostConnected) {
    const fullEntity = getEntityByName(kbId, entity.name)
    if (!fullEntity) continue

    const rels = uniqueRelationships
      .filter(r => r.source === fullEntity.id || r.target === fullEntity.id)
      .map(r => {
        const otherId = r.source === fullEntity.id ? r.target : r.source
        const other = entityMap.get(otherId)?.name || otherId
        return `- ${r.source === fullEntity.id ? '→' : '←'} **${other}** (${r.keywords}): ${r.description}`
      }).join('\n')

    const chunkIds = entity.chunkIds || []
    const sourceContent = allChunks.filter(c => chunkIds.includes(c.id)).map(c => c.content).join('\n\n').substring(0, 6000)
    const sourceDocs = [...new Set(allChunks.filter(c => chunkIds.includes(c.id)).map(c => {
      const doc = documents.find(d => d.id === c.doc_id)
      return doc?.name || 'unknown'
    }))].join(', ')

    try {
      const pagePrompt = ENTITY_PAGE_PROMPT
        .replace('{name}', entity.name)
        .replace('{type}', entity.type)
        .replace('{description}', entity.description || 'No description available')
        .replace('{relationships}', rels || 'None')
        .replace('{source_docs}', sourceDocs)
        .replace('{source_content}', sourceContent)

      const pageResp = await aiChat([
        { role: 'system', content: 'You are a technical writer. Write detailed wiki pages in markdown.' },
        { role: 'user', content: pagePrompt }
      ], { model: options.model, provider: options.providerId })

      insertPage({
        id: `pg-${nanoid(10)}`, kb_id: kbId, entity_id: fullEntity.id,
        title: entity.name, content: pageResp, type: 'entity', metadata_json: null
      })
    } catch { /* individual page failure is non-fatal */ }
  }

  updateBuildProgress(progressId, {
    status: 'completed', completed_at: now(),
    total_entities: entityMap.size, total_relationships: uniqueRelationships.length
  })

  const stats = getWikiStats(kbId)
  onProgress?.({ type: 'complete', entities: stats.entities, relationships: stats.relationships })

  return { entities: stats.entities, relationships: stats.relationships, pages: stats.pages }
}

// ==================== Helpers ====================

function dedupRelationships(rels: Array<{ source: string; target: string; keywords: string; description: string; chunkIds: string[] }>) {
  const map = new Map<string, typeof rels[0]>()
  for (const rel of rels) {
    const key = [rel.source, rel.target].sort().join(':')
    const existing = map.get(key)
    if (existing) {
      existing.chunkIds = [...new Set([...existing.chunkIds, ...rel.chunkIds])]
      if (rel.description.length > existing.description.length) existing.description = rel.description
      if (rel.keywords && !existing.keywords.includes(rel.keywords)) existing.keywords += `, ${rel.keywords}`
    } else {
      map.set(key, { ...rel })
    }
  }
  return Array.from(map.values())
}

function now(): number { return Date.now() }
