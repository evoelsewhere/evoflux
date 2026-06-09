import { getDatabase } from './database'
import { nanoid } from 'nanoid'
import { vectorToBuffer, bufferToVector, cosineSimilarity } from '../memory/embedding'

function now(): number { return Date.now() }

export interface WikiEntity {
  id: string
  kb_id: string
  name: string
  type: string
  summary: string | null
  description: string | null
  chunk_ids: string | null
  embedding: Uint8Array | null
  metadata_json: string | null
  created_at: number
  updated_at: number
}

export interface WikiRelationship {
  id: string
  kb_id: string
  source_entity_id: string
  target_entity_id: string
  type: string
  label: string | null
  weight: number
  chunk_ids: string | null
  metadata_json: string | null
  created_at: number
}

export interface WikiPage {
  id: string
  kb_id: string
  entity_id: string | null
  title: string
  content: string
  type: string
  metadata_json: string | null
  created_at: number
  updated_at: number
}

export interface WikiBuildProgress {
  id: string
  kb_id: string
  status: string
  total_batches: number
  completed_batches: number
  failed_batches: number
  total_entities: number
  total_relationships: number
  started_at: number
  completed_at: number | null
  error_log: string | null
}

// ==================== Entities ====================

export function insertEntity(entity: Omit<WikiEntity, 'created_at' | 'updated_at'>): string {
  const ts = now()
  getDatabase().prepare(
    'INSERT INTO wiki_entities (id, kb_id, name, type, summary, description, chunk_ids, embedding, metadata_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
  ).run(entity.id, entity.kb_id, entity.name, entity.type, entity.summary, entity.description, entity.chunk_ids, entity.embedding, entity.metadata_json, ts, ts)
  return entity.id
}

export function getEntity(id: string): WikiEntity | undefined {
  return getDatabase().prepare('SELECT * FROM wiki_entities WHERE id = ?').get(id) as unknown as WikiEntity | undefined
}

export function getEntityByName(kbId: string, name: string): WikiEntity | undefined {
  return getDatabase().prepare('SELECT * FROM wiki_entities WHERE kb_id = ? AND LOWER(name) = LOWER(?)').get(kbId, name) as unknown as WikiEntity | undefined
}

export function listEntities(kbId: string, type?: string): WikiEntity[] {
  if (type) {
    return getDatabase().prepare('SELECT * FROM wiki_entities WHERE kb_id = ? AND type = ? ORDER BY name').all(kbId, type) as unknown as WikiEntity[]
  }
  return getDatabase().prepare('SELECT * FROM wiki_entities WHERE kb_id = ? ORDER BY name').all(kbId) as unknown as WikiEntity[]
}

export function updateEntity(id: string, patch: Partial<WikiEntity>): void {
  const entity = getEntity(id)
  if (!entity) return
  getDatabase().prepare(
    'UPDATE wiki_entities SET name = ?, type = ?, summary = ?, description = ?, chunk_ids = ?, metadata_json = ?, updated_at = ? WHERE id = ?'
  ).run(
    patch.name ?? entity.name, patch.type ?? entity.type,
    patch.summary ?? entity.summary, patch.description ?? entity.description,
    patch.chunk_ids ?? entity.chunk_ids, patch.metadata_json ?? entity.metadata_json,
    now(), id
  )
}

export function deleteEntity(id: string): void {
  getDatabase().prepare('DELETE FROM wiki_entities WHERE id = ?').run(id)
}

export function deleteEntitiesByKB(kbId: string): void {
  getDatabase().prepare('DELETE FROM wiki_entities WHERE kb_id = ?').run(kbId)
}

export function countEntities(kbId: string): number {
  try {
    const row = getDatabase().prepare('SELECT COUNT(*) as cnt FROM wiki_entities WHERE kb_id = ?').get(kbId) as { cnt: number } | undefined
    return row?.cnt ?? 0
  } catch { return 0 }
}

// ==================== Entity-Chunks ====================

export function linkEntityChunks(entityId: string, chunkIds: string[], batchIndex?: number): void {
  const ts = now()
  const stmt = getDatabase().prepare('INSERT OR IGNORE INTO wiki_entity_chunks (entity_id, chunk_id, batch_index, processed_at) VALUES (?, ?, ?, ?)')
  for (const chunkId of chunkIds) {
    stmt.run(entityId, chunkId, batchIndex ?? null, ts)
  }
}

export function getLinkedChunkIds(chunkIds: string[]): string[] {
  if (chunkIds.length === 0) return []
  const placeholders = chunkIds.map(() => '?').join(',')
  const rows = getDatabase().prepare(
    `SELECT DISTINCT chunk_id FROM wiki_entity_chunks WHERE chunk_id IN (${placeholders})`
  ).all(...chunkIds) as { chunk_id: string }[]
  return rows.map(r => r.chunk_id)
}

export function getEntityChunkIds(entityId: string): string[] {
  const rows = getDatabase().prepare('SELECT chunk_id FROM wiki_entity_chunks WHERE entity_id = ?').all(entityId) as { chunk_id: string }[]
  return rows.map(r => r.chunk_id)
}

export function mergeEntityChunks(entityId: string, newChunkIds: string[], batchIndex?: number): void {
  const existing = new Set(getEntityChunkIds(entityId))
  const toAdd = newChunkIds.filter(id => !existing.has(id))
  if (toAdd.length > 0) linkEntityChunks(entityId, toAdd, batchIndex)
}

// ==================== Relationships ====================

export function insertRelationship(rel: Omit<WikiRelationship, 'created_at'>): string {
  const ts = now()
  getDatabase().prepare(
    'INSERT INTO wiki_relationships (id, kb_id, source_entity_id, target_entity_id, type, label, weight, chunk_ids, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
  ).run(rel.id, rel.kb_id, rel.source_entity_id, rel.target_entity_id, rel.type, rel.label, rel.weight, rel.chunk_ids, rel.metadata_json, ts)
  return rel.id
}

export function getRelationship(id: string): WikiRelationship | undefined {
  return getDatabase().prepare('SELECT * FROM wiki_relationships WHERE id = ?').get(id) as unknown as WikiRelationship | undefined
}

export function listRelationships(kbId: string, entityId?: string): WikiRelationship[] {
  if (entityId) {
    return getDatabase().prepare(
      'SELECT * FROM wiki_relationships WHERE kb_id = ? AND (source_entity_id = ? OR target_entity_id = ?) ORDER BY weight DESC'
    ).all(kbId, entityId, entityId) as unknown as WikiRelationship[]
  }
  return getDatabase().prepare('SELECT * FROM wiki_relationships WHERE kb_id = ? ORDER BY weight DESC').all(kbId) as unknown as WikiRelationship[]
}

export function deleteRelationshipsByKB(kbId: string): void {
  getDatabase().prepare('DELETE FROM wiki_relationships WHERE kb_id = ?').run(kbId)
}

export function countRelationships(kbId: string): number {
  try {
    const row = getDatabase().prepare('SELECT COUNT(*) as cnt FROM wiki_relationships WHERE kb_id = ?').get(kbId) as { cnt: number } | undefined
    return row?.cnt ?? 0
  } catch { return 0 }
}

// ==================== Pages ====================

export function insertPage(page: Omit<WikiPage, 'created_at' | 'updated_at'>): string {
  const ts = now()
  getDatabase().prepare(
    'INSERT INTO wiki_pages (id, kb_id, entity_id, title, content, type, metadata_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
  ).run(page.id, page.kb_id, page.entity_id, page.title, page.content, page.type, page.metadata_json, ts, ts)
  return page.id
}

export function getPage(id: string): WikiPage | undefined {
  return getDatabase().prepare('SELECT * FROM wiki_pages WHERE id = ?').get(id) as unknown as WikiPage | undefined
}

export function getPageByEntity(entityId: string): WikiPage | undefined {
  return getDatabase().prepare('SELECT * FROM wiki_pages WHERE entity_id = ?').get(entityId) as unknown as WikiPage | undefined
}

export function getOverviewPage(kbId: string): WikiPage | undefined {
  return getDatabase().prepare("SELECT * FROM wiki_pages WHERE kb_id = ? AND type = 'overview'").get(kbId) as unknown as WikiPage | undefined
}

export function listPages(kbId: string): WikiPage[] {
  return getDatabase().prepare('SELECT * FROM wiki_pages WHERE kb_id = ? ORDER BY type, title').all(kbId) as unknown as WikiPage[]
}

export function deletePagesByKB(kbId: string): void {
  getDatabase().prepare('DELETE FROM wiki_pages WHERE kb_id = ?').run(kbId)
}

// ==================== Build Progress ====================

export function createBuildProgress(kbId: string, totalBatches: number): string {
  const id = `wbp-${nanoid(10)}`
  const ts = now()
  getDatabase().prepare(
    'INSERT INTO wiki_build_progress (id, kb_id, status, total_batches, completed_batches, failed_batches, total_entities, total_relationships, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
  ).run(id, kbId, 'building', totalBatches, 0, 0, 0, 0, ts)
  return id
}

export function updateBuildProgress(id: string, patch: Partial<WikiBuildProgress>): void {
  const row = getDatabase().prepare('SELECT * FROM wiki_build_progress WHERE id = ?').get(id) as unknown as WikiBuildProgress | undefined
  if (!row) return
  getDatabase().prepare(
    'UPDATE wiki_build_progress SET status = ?, completed_batches = ?, failed_batches = ?, total_entities = ?, total_relationships = ?, completed_at = ?, error_log = ? WHERE id = ?'
  ).run(
    patch.status ?? row.status,
    patch.completed_batches ?? row.completed_batches,
    patch.failed_batches ?? row.failed_batches,
    patch.total_entities ?? row.total_entities,
    patch.total_relationships ?? row.total_relationships,
    patch.completed_at ?? row.completed_at,
    patch.error_log ?? row.error_log,
    id
  )
}

export function getLatestBuildProgress(kbId: string): WikiBuildProgress | undefined {
  return getDatabase().prepare('SELECT * FROM wiki_build_progress WHERE kb_id = ? ORDER BY started_at DESC LIMIT 1').get(kbId) as unknown as WikiBuildProgress | undefined
}

// ==================== Search ====================

export function searchEntities(kbId: string, query: string, limit: number = 20): WikiEntity[] {
  return getDatabase().prepare(
    'SELECT * FROM wiki_entities WHERE kb_id = ? AND (LOWER(name) LIKE ? OR LOWER(summary) LIKE ?) ORDER BY name LIMIT ?'
  ).all(kbId, `%${query.toLowerCase()}%`, `%${query.toLowerCase()}%`, limit) as unknown as WikiEntity[]
}

export function searchEntitiesByVector(kbId: string, queryEmbedding: Float32Array, limit: number = 10): Array<WikiEntity & { score: number }> {
  const rows = getDatabase().prepare(
    'SELECT * FROM wiki_entities WHERE kb_id = ? AND embedding IS NOT NULL'
  ).all(kbId) as unknown as WikiEntity[]

  const results: Array<WikiEntity & { score: number }> = []
  const qNorm = vecNorm(queryEmbedding)

  for (const row of rows) {
    if (!row.embedding) continue
    const chunkVec = bufferToVector(row.embedding as unknown as Buffer)
    const score = cosineSimilarityFast(queryEmbedding, qNorm, chunkVec)
    results.push({ ...row, score })
  }

  results.sort((a, b) => b.score - a.score)
  return results.slice(0, limit)
}

function vecNorm(v: Float32Array): number {
  let sum = 0
  for (let i = 0; i < v.length; i++) sum += v[i] * v[i]
  return Math.sqrt(sum)
}

function cosineSimilarityFast(a: Float32Array, aNorm: number, b: Float32Array): number {
  let dot = 0
  let bNorm = 0
  const len = Math.min(a.length, b.length)
  for (let i = 0; i < len; i++) { dot += a[i] * b[i]; bNorm += b[i] * b[i] }
  const denom = aNorm * Math.sqrt(bNorm)
  return denom === 0 ? 0 : dot / denom
}

// ==================== Cleanup ====================

export function deleteWikiByKB(kbId: string): void {
  deletePagesByKB(kbId)
  deleteRelationshipsByKB(kbId)
  deleteEntitiesByKB(kbId)
  getDatabase().prepare('DELETE FROM wiki_entity_chunks WHERE entity_id IN (SELECT id FROM wiki_entities WHERE kb_id = ?)').run(kbId)
  getDatabase().prepare('DELETE FROM wiki_build_progress WHERE kb_id = ?').run(kbId)
}

// ==================== Stats ====================

export function getWikiStats(kbId: string): { entities: number; relationships: number; pages: number; built: boolean } {
  try {
    const entities = countEntities(kbId)
    const relationships = countRelationships(kbId)
    const pages = getDatabase().prepare('SELECT COUNT(*) as cnt FROM wiki_pages WHERE kb_id = ?').get(kbId) as { cnt: number } | undefined
    const progress = getLatestBuildProgress(kbId)
    return { entities, relationships, pages: pages?.cnt ?? 0, built: progress?.status === 'completed' }
  } catch {
    return { entities: 0, relationships: 0, pages: 0, built: false }
  }
}
