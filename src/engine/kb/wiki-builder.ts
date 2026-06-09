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
  maxEntities?: number
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

type ExtractedEntity = { name: string; type: string; summary: string; details?: string; aliases?: string[]; importance?: number }
type ExtractedRelationship = { source: string; target: string; type: string; description?: string; weight?: number }

const SUMMARIZE_PROMPT = `You are a technical analyst. Analyze this document and extract structured knowledge.

Document: {docName}

Content:
{content}

Extract in JSON format:
{
  "summary": "2-3 sentence summary of what this document covers",
  "entities": [
    {
      "name": "EntityName",
      "type": "concept|api|class|function|config|tool|pattern",
      "summary": "Clear 1-2 sentence description",
      "details": "Key details, usage notes, important facts",
      "importance": 0.0-1.0
    }
  ],
  "relationships": [
    {
      "source": "EntityA",
      "target": "EntityB",
      "type": "depends_on|part_of|uses|extends|related_to|alternative_to",
      "description": "Clear description of how they relate"
    }
  ]
}

Rules:
- Extract ONLY significant, specific entities (not generic words)
- Entity names should be proper nouns or specific technical terms
- Include code examples in details if relevant
- Relationships must be between entities you extracted
- Be thorough but precise
- Output valid JSON only`

const OVERVIEW_PROMPT = `You are a technical writer creating a wiki overview page.

Knowledge Base: {kbName}

Document Summaries:
{summaries}

Key Entities ({entityCount} total):
{entities}

Key Relationships:
{relationships}

Write a comprehensive wiki overview page in markdown:

# Overview

[2-3 paragraph executive summary]

## Key Concepts

[Group and describe the main concepts, each as a subsection]

## Architecture

[Describe the overall structure and how components relate]

## Quick Reference

[Table: Name | Type | Description]

## Getting Started

[Brief guide on where to start reading]

Use proper markdown formatting. Be factual and concise. Do not use code blocks for the overview text.`

const ENTITY_PAGE_PROMPT = `You are a technical writer creating a wiki page for a specific entity.

Entity: {name}
Type: {type}
Summary: {summary}
Details: {details}

Related Entities:
{relatedEntities}

Source Documents:
{sourceDocs}

Source Content (relevant excerpts):
{sourceContent}

Write a detailed wiki page in markdown:

# {name}

[Comprehensive description - 3-5 paragraphs]

## Key Details

[Important facts, parameters, configurations]

## Usage

[How to use, examples if applicable]

## Related Topics

[Links to related entities with brief descriptions]

## References

[Source document names]

Use proper markdown formatting. Be thorough and accurate. Include code examples where relevant.`

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

  const entityMap = new Map<string, { entityId: string; name: string; type: string; summary: string; details: string }>()
  const allRelationships: Array<{ source: string; target: string; type: string; description: string; chunkIds: string[] }> = []
  const documentSummaries: Array<{ name: string; summary: string }> = []
  let failedDocs = 0

  async function processDocument(docIdx: number): Promise<void> {
    const doc = documents[docIdx]
    const docChunks = chunkMap.get(doc.id) || []
    if (docChunks.length === 0) return

    const content = docChunks.map(c => c.content).join('\n\n').substring(0, 30000)
    const chunkIds = docChunks.map(c => c.id)

    try {
      const prompt = SUMMARIZE_PROMPT
        .replace('{docName}', doc.name)
        .replace('{content}', content)

      const response = await aiChat([
        { role: 'system', content: 'You are a knowledge extraction engine. Output valid JSON only, no markdown.' },
        { role: 'user', content: prompt }
      ], { model: options.model, provider: options.providerId })

      const parsed = parseJSON(response)
      if (!parsed) return

      documentSummaries.push({ name: doc.name, summary: parsed.summary || '' })

      for (const entity of (parsed.entities || [])) {
        if (!entity.name || !entity.type) continue

        const existing = entityMap.get(entity.name.toLowerCase())
        if (existing) {
          const existingEntity = getEntityByName(kbId, entity.name)
          if (existingEntity) {
            mergeEntityChunks(existingEntity.id, chunkIds)
            if (entity.details && (!existing.details || entity.details.length > existing.details.length)) {
              existing.details = entity.details
              existing.summary = entity.summary || existing.summary
            }
          }
        } else {
          const entityId = `ent-${nanoid(10)}`
          let embBuf: Buffer | null = null
          try {
            const emb = await embed(`${entity.name}: ${entity.summary || ''}`, 'passage')
            embBuf = Buffer.from(emb.buffer)
          } catch { /* skip embedding */ }

          insertEntity({
            id: entityId, kb_id: kbId, name: entity.name, type: entity.type,
            summary: entity.summary || '', description: entity.details || '',
            chunk_ids: JSON.stringify(chunkIds), embedding: embBuf,
            metadata_json: JSON.stringify({ importance: entity.importance || 0.5 })
          })
          linkEntityChunks(entityId, chunkIds)
          entityMap.set(entity.name.toLowerCase(), {
            entityId, name: entity.name, type: entity.type,
            summary: entity.summary || '', details: entity.details || ''
          })
        }
      }

      for (const rel of (parsed.relationships || [])) {
        const srcEntity = entityMap.get(rel.source?.toLowerCase())
        const tgtEntity = entityMap.get(rel.target?.toLowerCase())
        if (srcEntity && tgtEntity) {
          allRelationships.push({
            source: srcEntity.entityId, target: tgtEntity.entityId,
            type: rel.type || 'related_to', description: rel.description || '',
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

  onProgress?.({ type: 'merge', entities: entityMap.size, relationships: allRelationships.length })

  const uniqueRelationships = dedupRelationships(allRelationships)
  for (const rel of uniqueRelationships) {
    insertRelationship({
      id: `rel-${nanoid(10)}`, kb_id: kbId,
      source_entity_id: rel.source, target_entity_id: rel.target,
      type: rel.type, label: rel.description, weight: 0.8,
      chunk_ids: JSON.stringify(rel.chunkIds), metadata_json: null
    })
  }

  onProgress?.({ type: 'page', entities: entityMap.size, relationships: uniqueRelationships.length })

  const entitiesList = Array.from(entityMap.values())
  const topEntities = entitiesList.sort((a, b) => (b.details?.length || 0) - (a.details?.length || 0)).slice(0, 30)

  try {
    const overviewPrompt = OVERVIEW_PROMPT
      .replace('{kbName}', documents[0]?.path?.split('/').slice(0, -1).join('/') || 'Knowledge Base')
      .replace('{summaries}', documentSummaries.slice(0, 50).map(s => `- ${s.name}: ${s.summary}`).join('\n'))
      .replace('{entityCount}', String(entitiesList.length))
      .replace('{entities}', topEntities.slice(0, 50).map(e => `- **${e.name}** (${e.type}): ${e.summary}`).join('\n'))
      .replace('{relationships}', uniqueRelationships.slice(0, 30).map(r => {
        const src = entityMap.get(r.source)?.name || r.source
        const tgt = entityMap.get(r.target)?.name || r.target
        return `- ${src} → ${tgt} (${r.type}): ${r.description}`
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

  for (const entity of topEntities.slice(0, 20)) {
    const fullEntity = getEntityByName(kbId, entity.name)
    if (!fullEntity) continue

    const related = uniqueRelationships
      .filter(r => r.source === fullEntity.id || r.target === fullEntity.id)
      .map(r => {
        const otherId = r.source === fullEntity.id ? r.target : r.source
        const other = entityMap.get(otherId)?.name || otherId
        return `- ${r.source === fullEntity.id ? '→' : '←'} **${other}** (${r.type}): ${r.description}`
      }).join('\n')

    const chunkIds = JSON.parse(fullEntity.chunk_ids || '[]') as string[]
    const sourceContent = allChunks.filter(c => chunkIds.includes(c.id)).map(c => c.content).join('\n\n').substring(0, 8000)
    const sourceDocs = [...new Set(allChunks.filter(c => chunkIds.includes(c.id)).map(c => {
      const doc = documents.find(d => d.id === c.doc_id)
      return doc?.name || 'unknown'
    }))].join(', ')

    try {
      const pagePrompt = ENTITY_PAGE_PROMPT
        .replace('{name}', entity.name)
        .replace('{type}', entity.type)
        .replace('{summary}', entity.summary)
        .replace('{details}', entity.details || 'No additional details')
        .replace('{relatedEntities}', related || 'None')
        .replace('{sourceDocs}', sourceDocs)
        .replace('{sourceContent}', sourceContent.substring(0, 6000))

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

function parseJSON(text: string): { summary?: string; entities?: ExtractedEntity[]; relationships?: ExtractedRelationship[] } | null {
  try {
    const match = text.match(/\{[\s\S]*\}/)
    const raw = match ? JSON.parse(match[0]) : JSON.parse(text)
    return {
      summary: typeof raw.summary === 'string' ? raw.summary : undefined,
      entities: Array.isArray(raw.entities) ? raw.entities : [],
      relationships: Array.isArray(raw.relationships) ? raw.relationships : []
    }
  } catch { return null }
}

function dedupRelationships(rels: Array<{ source: string; target: string; type: string; description: string; chunkIds: string[] }>) {
  const map = new Map<string, typeof rels[0]>()
  for (const rel of rels) {
    const key = `${rel.source}:${rel.target}:${rel.type}`
    const existing = map.get(key)
    if (existing) {
      existing.chunkIds = [...new Set([...existing.chunkIds, ...rel.chunkIds])]
      if (rel.description.length > existing.description.length) existing.description = rel.description
    } else {
      map.set(key, { ...rel })
    }
  }
  return Array.from(map.values())
}

function now(): number { return Date.now() }
