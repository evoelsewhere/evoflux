import { nanoid } from 'nanoid'
import { listChunksByKB, type KBChunkRow } from '../db/kb-repo'
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
  batchSize?: number
  maxEntities?: number
}

export interface WikiProgress {
  type: 'start' | 'batch' | 'entity' | 'page' | 'complete' | 'error'
  batch?: number
  total?: number
  entities?: number
  relationships?: number
  saved?: boolean
  error?: string
}

const BATCH_SIZE = 50
const PARALLEL_WORKERS = 3

type ExtractedEntity = { name: string; type: string; summary: string; aliases?: string[]; importance?: number }
type ExtractedRelationship = { source: string; target: string; type: string; label: string; weight?: number }

const EXTRACT_SYSTEM_PROMPT = `You are a knowledge extraction engine. Extract structured information from documents.

Rules:
- Extract ONLY concrete, meaningful entities (not generic words)
- Entity types: concept, api, class, function, config, tool, pattern
- Relationships: depends_on, part_of, uses, extends, related_to, alternative_to
- Be precise and concise
- Output valid JSON only, no markdown`

function extractUserPrompt(content: string): string {
  return `Extract all entities and relationships from this document.

Document content:
${content.substring(0, 8000)}

Output JSON format:
{
  "entities": [
    { "name": "EntityName", "type": "concept", "summary": "1-2 sentence description", "aliases": ["alt name"], "importance": 0.8 }
  ],
  "relationships": [
    { "source": "EntityA", "target": "EntityB", "type": "depends_on", "label": "human-readable description", "weight": 0.8 }
  ]
}

If no entities found, return {"entities": [], "relationships": []}`
}

function summarizePrompt(entities: Array<{ name: string; type: string; summary: string }>, relationships: Array<{ source: string; target: string; type: string; label: string }>): string {
  return `Generate a brief overview wiki page for a knowledge base.

Entities (${entities.length}):
${entities.map(e => `- ${e.name} (${e.type}): ${e.summary}`).join('\n')}

Key relationships:
${relationships.slice(0, 50).map(r => `- ${r.source} → ${r.target} (${r.type}: ${r.label})`).join('\n')}

Write a markdown overview page with:
1. Executive summary (2-3 sentences)
2. Key topics grouped by type
3. Quick reference table (name | type | summary)

Keep it concise. No code blocks, no unnecessary formatting.`
}

function entityPagePrompt(entity: { name: string; type: string; summary: string }, relatedEntities: string[], chunkContents: string[]): string {
  return `Generate a wiki page for entity "${entity.name}".

Type: ${entity.type}
Summary: ${entity.summary}
Related: ${relatedEntities.join(', ')}

Source content:
${chunkContents.map(c => c.substring(0, 1000)).join('\n---\n').substring(0, 6000)}

Write a wiki page in markdown:
1. Overview (2-3 sentences)
2. Key details
3. Usage/examples (if applicable)
4. Related topics

Keep it concise and factual.`
}

export async function buildWiki(
  kbId: string,
  options: WikiBuilderOptions,
  aiChat: (messages: Array<{ role: string; content: string }>, opts?: { model?: string; provider?: string }) => Promise<string>,
  onProgress?: (progress: WikiProgress) => void
): Promise<{ entities: number; relationships: number; pages: number }> {
  const batchSize = options.batchSize || BATCH_SIZE

  deleteWikiByKB(kbId)

  const allChunks = listChunksByKB(kbId)
  if (allChunks.length === 0) {
    onProgress?.({ type: 'complete', entities: 0, relationships: 0 })
    return { entities: 0, relationships: 0, pages: 0 }
  }

  const batches: KBChunkRow[][] = []
  for (let i = 0; i < allChunks.length; i += batchSize) {
    batches.push(allChunks.slice(i, i + batchSize))
  }

  const progressId = createBuildProgress(kbId, batches.length)
  onProgress?.({ type: 'start', total: batches.length })

  const entityMap = new Map<string, { entityId: string; name: string; type: string; summary: string }>()
  const allRelationships: Array<{ source: string; target: string; type: string; label: string; weight: number; chunkIds: string[] }> = []
  let failedBatches = 0
  let errorLog: Array<{ batch: number; error: string }> = []

  async function processBatch(batchIdx: number): Promise<{ entities: ExtractedEntity[]; relationships: ExtractedRelationship[]; batchIds: string[] } | null> {
    const batch = batches[batchIdx]
    const batchIds = batch.map(c => c.id)

    const alreadyLinked = getLinkedChunkIds(batchIds)
    if (alreadyLinked.length === batchIds.length) {
      onProgress?.({ type: 'batch', batch: batchIdx, total: batches.length, saved: false })
      return null
    }

    try {
      const content = batch.map(c => c.content).join('\n---\n')
      const response = await aiChat([
        { role: 'system', content: EXTRACT_SYSTEM_PROMPT },
        { role: 'user', content: extractUserPrompt(content) }
      ], { model: options.model, provider: options.providerId })

      const parsed = parseExtractResult(response)
      onProgress?.({ type: 'batch', batch: batchIdx, total: batches.length, entities: parsed.entities.length, relationships: parsed.relationships.length, saved: true })
      return { ...parsed, batchIds }
    } catch (error) {
      failedBatches++
      errorLog.push({ batch: batchIdx, error: error instanceof Error ? error.message : String(error) })
      updateBuildProgress(progressId, { failed_batches: failedBatches, error_log: JSON.stringify(errorLog) })
      onProgress?.({ type: 'error', batch: batchIdx, error: error instanceof Error ? error.message : String(error) })
      return null
    }
  }

  for (let i = 0; i < batches.length; i += PARALLEL_WORKERS) {
    const chunk = batches.slice(i, i + PARALLEL_WORKERS)
    const indices = chunk.map((_, j) => i + j)
    const results = await Promise.all(indices.map(idx => processBatch(idx)))

    for (const result of results) {
      if (!result) continue

      for (const entity of result.entities) {
        const existingFromMap = entityMap.get(entity.name.toLowerCase())
        const existingFromDB = getEntityByName(kbId, entity.name)
        const existingEntityId = existingFromMap?.entityId || existingFromDB?.id
        if (existingEntityId) {
          mergeEntityChunks(existingEntityId, result.batchIds, i)
          entityMap.set(entity.name.toLowerCase(), { entityId: existingEntityId, name: entity.name, type: entity.type, summary: entity.summary })
        } else {
          const entityId = `ent-${nanoid(10)}`
          try {
            const embedding = await embed(`${entity.name}: ${entity.summary}`, 'passage')
            insertEntity({
              id: entityId, kb_id: kbId, name: entity.name, type: entity.type,
              summary: entity.summary, description: null,
              chunk_ids: JSON.stringify(result.batchIds),
              embedding: Buffer.from(embedding.buffer),
              metadata_json: JSON.stringify({ aliases: entity.aliases || [], importance: entity.importance || 0.5 })
            })
          } catch {
            insertEntity({
              id: entityId, kb_id: kbId, name: entity.name, type: entity.type,
              summary: entity.summary, description: null,
              chunk_ids: JSON.stringify(result.batchIds),
              embedding: null,
              metadata_json: JSON.stringify({ aliases: entity.aliases || [], importance: entity.importance || 0.5 })
            })
          }
          linkEntityChunks(entityId, result.batchIds, i)
          entityMap.set(entity.name.toLowerCase(), { entityId, name: entity.name, type: entity.type, summary: entity.summary })
        }
      }

      for (const rel of result.relationships) {
        const srcEntity = entityMap.get(rel.source.toLowerCase())
        const tgtEntity = entityMap.get(rel.target.toLowerCase())
        if (srcEntity && tgtEntity) {
          allRelationships.push({
            source: srcEntity.entityId, target: tgtEntity.entityId,
            type: rel.type, label: rel.label, weight: rel.weight || 0.5,
            chunkIds: result.batchIds
          })
        }
      }
    }

    updateBuildProgress(progressId, {
      completed_batches: Math.min(i + PARALLEL_WORKERS, batches.length),
      total_entities: entityMap.size,
      total_relationships: allRelationships.length
    })
  }

  const uniqueRelationships = dedupRelationships(allRelationships)
  for (const rel of uniqueRelationships) {
    insertRelationship({
      id: `rel-${nanoid(10)}`, kb_id: kbId,
      source_entity_id: rel.source, target_entity_id: rel.target,
      type: rel.type, label: rel.label, weight: rel.weight,
      chunk_ids: JSON.stringify(rel.chunkIds), metadata_json: null
    })
  }

  onProgress?.({ type: 'page', entities: entityMap.size, relationships: uniqueRelationships.length })

  const entitiesList = Array.from(entityMap.values())
  try {
    const overviewResp = await aiChat([
      { role: 'system', content: 'You are a technical writer. Write concise wiki pages in markdown.' },
      { role: 'user', content: summarizePrompt(entitiesList, uniqueRelationships.map(r => ({ source: entityMap.get(r.source)?.name || r.source, target: entityMap.get(r.target)?.name || r.target, type: r.type, label: r.label || '' }))) }
    ], { model: options.model, provider: options.providerId })

    insertPage({
      id: `pg-${nanoid(10)}`, kb_id: kbId, entity_id: null,
      title: 'Overview', content: overviewResp, type: 'overview', metadata_json: null
    })
  } catch { /* overview page is optional */ }

  const topEntities = entitiesList.sort((a, b) => {
    const aMeta = JSON.parse(getEntityByName(kbId, a.name)?.metadata_json || '{}')
    const bMeta = JSON.parse(getEntityByName(kbId, b.name)?.metadata_json || '{}')
    return (bMeta.importance || 0.5) - (aMeta.importance || 0.5)
  }).slice(0, 20)

  for (const entity of topEntities) {
    const fullEntity = getEntityByName(kbId, entity.name)
    if (!fullEntity) continue

    const related = uniqueRelationships
      .filter(r => r.source === fullEntity.id || r.target === fullEntity.id)
      .map(r => r.source === fullEntity.id ? entityMap.get(r.target)?.name : entityMap.get(r.source)?.name)
      .filter(Boolean) as string[]

    const chunkIds = JSON.parse(fullEntity.chunk_ids || '[]') as string[]
    const chunkContents = allChunks.filter(c => chunkIds.includes(c.id)).map(c => c.content)

    try {
      const pageResp = await aiChat([
        { role: 'system', content: 'You are a technical writer. Write concise wiki pages in markdown.' },
        { role: 'user', content: entityPagePrompt(entity, related, chunkContents) }
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

function parseExtractResult(response: string): {
  entities: Array<{ name: string; type: string; summary: string; aliases?: string[]; importance?: number }>
  relationships: Array<{ source: string; target: string; type: string; label: string; weight?: number }>
} {
  let text = response.trim()

  const jsonMatch = text.match(/\{[\s\S]*\}/)
  if (jsonMatch) text = jsonMatch[0]

  try {
    const parsed = JSON.parse(text)
    return {
      entities: Array.isArray(parsed.entities) ? parsed.entities : [],
      relationships: Array.isArray(parsed.relationships) ? parsed.relationships : []
    }
  } catch {
    return { entities: [], relationships: [] }
  }
}

function dedupRelationships(rels: Array<{ source: string; target: string; type: string; label: string; weight: number; chunkIds: string[] }>) {
  const map = new Map<string, typeof rels[0]>()
  for (const rel of rels) {
    const key = `${rel.source}:${rel.target}:${rel.type}`
    const existing = map.get(key)
    if (existing) {
      existing.weight = Math.max(existing.weight, rel.weight)
      existing.chunkIds = [...new Set([...existing.chunkIds, ...rel.chunkIds])]
    } else {
      map.set(key, { ...rel })
    }
  }
  return Array.from(map.values())
}

function now(): number { return Date.now() }
