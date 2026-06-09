import { getDatabase } from './database'
import { nanoid } from 'nanoid'
import { bufferToVector, cosineSimilarity, vectorToBuffer } from '../memory/embedding'

function now(): number { return Date.now() }

// ==================== Knowledge Bases ====================

export interface KBRow {
  id: string
  name: string
  description: string
  config_json: string
  stats_json: string
  created_at: number
  updated_at: number
}

export interface KBSourceRow {
  id: string
  kb_id: string
  path: string
  type: string
  status: string
  file_count: number
  error: string | null
  git_repo_path: string | null
  git_branch: string | null
  git_commit_hash: string | null
  git_synced_at: number | null
  auto_sync: number
  created_at: number
}

export interface KBDocumentRow {
  id: string
  kb_id: string
  source_id: string | null
  path: string
  name: string
  extension: string | null
  size: number | null
  content_preview: string | null
  chunk_count: number
  status: string
  error: string | null
  git_status: string
  indexed_content_hash: string | null
  current_content_hash: string | null
  git_diff_preview: string | null
  created_at: number
}

export interface KBChunkRow {
  id: string
  doc_id: string
  kb_id: string
  chunk_index: number | null
  content: string
  embedding: Uint8Array | null
  metadata_json: string | null
  created_at: number
}

export interface SearchResult {
  chunk_id: string
  doc_id: string
  kb_id: string
  content: string
  metadata_json: string | null
  vector_score: number
  bm25_score: number
  hybrid_score: number
  doc_name: string
  doc_path: string
  doc_extension: string | null
}

export interface KBStats {
  totalDocs: number
  indexedDocs: number
  totalChunks: number
  totalSize: number
  indexedPercent: number
}

// ==================== KB CRUD ====================

export function createKB(name: string, description?: string, config?: Record<string, unknown>): KBRow {
  const id = `kb-${nanoid(10)}`
  const ts = now()
  const configJson = JSON.stringify(config || { chunkSize: 1000, chunkOverlap: 200, strategy: 'auto' })
  getDatabase().prepare(
    'INSERT INTO knowledge_bases (id, name, description, config_json, stats_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)'
  ).run(id, name, description || '', configJson, '{}', ts, ts)
  return getKB(id)!
}

export function getKB(id: string): KBRow | undefined {
  return getDatabase().prepare('SELECT * FROM knowledge_bases WHERE id = ?').get(id) as unknown as KBRow | undefined
}

export function listKBs(): KBRow[] {
  return getDatabase().prepare('SELECT * FROM knowledge_bases ORDER BY updated_at DESC').all() as unknown as KBRow[]
}

export function updateKB(id: string, patch: { name?: string; description?: string; config?: Record<string, unknown> }): void {
  const kb = getKB(id)
  if (!kb) return
  const name = patch.name ?? kb.name
  const desc = patch.description ?? kb.description
  const config = patch.config ? JSON.stringify(patch.config) : kb.config_json
  getDatabase().prepare('UPDATE knowledge_bases SET name = ?, description = ?, config_json = ?, updated_at = ? WHERE id = ?')
    .run(name, desc, config, now(), id)
}

export function deleteKB(id: string): void {
  getDatabase().prepare('DELETE FROM knowledge_bases WHERE id = ?').run(id)
}

// ==================== Sources ====================

export function addSource(kbId: string, path: string, type: string): KBSourceRow {
  const id = `src-${nanoid(10)}`
  const ts = now()
  getDatabase().prepare(
    'INSERT INTO kb_sources (id, kb_id, path, type, status, created_at) VALUES (?, ?, ?, ?, ?, ?)'
  ).run(id, kbId, path, type, 'pending', ts)
  return getDatabase().prepare('SELECT * FROM kb_sources WHERE id = ?').get(id) as unknown as KBSourceRow
}

export function getSource(id: string): KBSourceRow | undefined {
  return getDatabase().prepare('SELECT * FROM kb_sources WHERE id = ?').get(id) as unknown as KBSourceRow | undefined
}

export function listSources(kbId: string): KBSourceRow[] {
  return getDatabase().prepare('SELECT * FROM kb_sources WHERE kb_id = ? ORDER BY created_at DESC').all(kbId) as unknown as KBSourceRow[]
}

export function updateSource(id: string, patch: Partial<KBSourceRow>): void {
  const src = getSource(id)
  if (!src) return
  getDatabase().prepare(
    'UPDATE kb_sources SET status = ?, file_count = ?, error = ?, git_repo_path = ?, git_branch = ?, git_commit_hash = ?, git_synced_at = ?, auto_sync = ? WHERE id = ?'
  ).run(
    patch.status ?? src.status,
    patch.file_count ?? src.file_count,
    patch.error ?? src.error,
    patch.git_repo_path ?? src.git_repo_path,
    patch.git_branch ?? src.git_branch,
    patch.git_commit_hash ?? src.git_commit_hash,
    patch.git_synced_at ?? src.git_synced_at,
    patch.auto_sync ?? src.auto_sync,
    id
  )
}

export function removeSource(id: string): void {
  getDatabase().prepare('DELETE FROM kb_sources WHERE id = ?').run(id)
}

// ==================== Documents ====================

export function addDocument(kbId: string, sourceId: string | null, path: string, name: string, ext: string | null, size: number | null): KBDocumentRow {
  const id = `doc-${nanoid(10)}`
  const ts = now()
  getDatabase().prepare(
    'INSERT INTO kb_documents (id, kb_id, source_id, path, name, extension, size, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
  ).run(id, kbId, sourceId, path, name, ext, size, 'pending', ts)
  return getDatabase().prepare('SELECT * FROM kb_documents WHERE id = ?').get(id) as unknown as KBDocumentRow
}

export function getDocument(id: string): KBDocumentRow | undefined {
  return getDatabase().prepare('SELECT * FROM kb_documents WHERE id = ?').get(id) as unknown as KBDocumentRow | undefined
}

export function listDocuments(kbId: string): KBDocumentRow[] {
  return getDatabase().prepare('SELECT * FROM kb_documents WHERE kb_id = ? ORDER BY name').all(kbId) as unknown as KBDocumentRow[]
}

export function updateDocument(id: string, patch: Partial<KBDocumentRow>): void {
  const doc = getDocument(id)
  if (!doc) return
  getDatabase().prepare(
    'UPDATE kb_documents SET status = ?, error = ?, content_preview = ?, chunk_count = ?, git_status = ?, indexed_content_hash = ?, current_content_hash = ?, git_diff_preview = ? WHERE id = ?'
  ).run(
    patch.status ?? doc.status,
    patch.error ?? doc.error,
    patch.content_preview ?? doc.content_preview,
    patch.chunk_count ?? doc.chunk_count,
    patch.git_status ?? doc.git_status,
    patch.indexed_content_hash ?? doc.indexed_content_hash,
    patch.current_content_hash ?? doc.current_content_hash,
    patch.git_diff_preview ?? doc.git_diff_preview,
    id
  )
}

export function removeDocument(id: string): void {
  getDatabase().prepare('DELETE FROM kb_documents WHERE id = ?').run(id)
}

export function removeDocumentsBySource(sourceId: string): void {
  getDatabase().prepare('DELETE FROM kb_documents WHERE source_id = ?').run(sourceId)
}

// ==================== Chunks ====================

export interface ChunkInsert {
  content: string
  embedding?: number[]
  metadata?: Record<string, unknown>
}

export function addChunks(docId: string, kbId: string, chunks: ChunkInsert[]): void {
  const db = getDatabase()
  const stmt = db.prepare('INSERT INTO kb_chunks (id, doc_id, kb_id, chunk_index, content, embedding, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)')
  const ts = now()
  for (let i = 0; i < chunks.length; i++) {
    const c = chunks[i]
    const embBuf = c.embedding ? vectorToBuffer(new Float32Array(c.embedding)) : null
    const metaJson = c.metadata ? JSON.stringify(c.metadata) : null
    stmt.run(`chk-${nanoid(10)}`, docId, kbId, i, c.content, embBuf, metaJson, ts)
  }
}

export function listChunks(docId: string): KBChunkRow[] {
  return getDatabase().prepare('SELECT * FROM kb_chunks WHERE doc_id = ? ORDER BY chunk_index').all(docId) as unknown as KBChunkRow[]
}

export function listChunksByKB(kbId: string): KBChunkRow[] {
  return getDatabase().prepare('SELECT * FROM kb_chunks WHERE kb_id = ? ORDER BY chunk_index').all(kbId) as unknown as KBChunkRow[]
}

export function removeChunksByDoc(docId: string): void {
  getDatabase().prepare('DELETE FROM kb_chunks WHERE doc_id = ?').run(docId)
}

export function removeChunksByKB(kbId: string): void {
  getDatabase().prepare('DELETE FROM kb_chunks WHERE kb_id = ?').run(kbId)
}

// ==================== Vector Search ====================

export interface VectorSearchOptions {
  limit?: number
  extensions?: string[]
  pathGlob?: string
  minScore?: number
}

export function searchChunksByVector(kbId: string, queryEmbedding: number[], options?: VectorSearchOptions | number): SearchResult[] {
  const limit = typeof options === 'number' ? options : options?.limit ?? 10
  const filters = typeof options === 'number' ? undefined : options
  const db = getDatabase()

  let sql = `
    SELECT c.id as chunk_id, c.doc_id, c.kb_id, c.content, c.metadata_json, c.embedding,
           d.name as doc_name, d.path as doc_path, d.extension as doc_extension
    FROM kb_chunks c
    JOIN kb_documents d ON c.doc_id = d.id
    WHERE c.kb_id = ? AND c.embedding IS NOT NULL
  `
  const params: unknown[] = [kbId]

  if (filters?.extensions && filters.extensions.length > 0) {
    const placeholders = filters.extensions.map(() => '?').join(',')
    sql += ` AND d.extension IN (${placeholders})`
    params.push(...filters.extensions)
  }

  const rows = db.prepare(sql).all(...params) as unknown as Array<KBChunkRow & { chunk_id: string; doc_name: string; doc_path: string; doc_extension: string | null }>

  const queryVec = new Float32Array(queryEmbedding)
  const queryNorm = vecNorm(queryVec)
  const minScore = filters?.minScore ?? 0

  const scored: Array<{ row: typeof rows[0]; score: number }> = []

  for (const row of rows) {
    if (filters?.pathGlob) {
      const pattern = filters.pathGlob.replace(/\*/g, '.*').replace(/\?/g, '.')
      if (!new RegExp(`^${pattern}$`, 'i').test(row.doc_path)) continue
    }

    const chunkVec = bufferToVector(row.embedding! as unknown as Buffer)
    const score = cosineSimilarityFast(queryVec, queryNorm, chunkVec)
    if (score >= minScore) scored.push({ row, score })
  }

  scored.sort((a, b) => b.score - a.score)

  return scored.slice(0, limit).map(({ row, score }) => ({
    chunk_id: row.chunk_id,
    doc_id: row.doc_id,
    kb_id: row.kb_id,
    content: row.content,
    metadata_json: row.metadata_json,
    vector_score: score,
    bm25_score: 0,
    hybrid_score: score,
    doc_name: row.doc_name,
    doc_path: row.doc_path,
    doc_extension: row.doc_extension
  }))
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
  for (let i = 0; i < len; i++) {
    dot += a[i] * b[i]
    bNorm += b[i] * b[i]
  }
  const denom = aNorm * Math.sqrt(bNorm)
  return denom === 0 ? 0 : dot / denom
}

// ==================== BM25 Search (LIKE-based) ====================

export function searchChunksByBM25(kbId: string, query: string, limit: number = 20): SearchResult[] {
  const db = getDatabase()

  const terms = query.toLowerCase().split(/\s+/).filter(t => t.length >= 2).slice(0, 5)
  if (terms.length === 0) return []

  const conditions = terms.map(() => 'LOWER(c.content) LIKE ?').join(' OR ')
  const params = terms.map(t => `%${t}%`)

  const rows = db.prepare(`
    SELECT c.id as chunk_id, c.doc_id, c.kb_id, c.content, c.metadata_json,
           d.name as doc_name, d.path as doc_path, d.extension as doc_extension
    FROM kb_chunks c
    JOIN kb_documents d ON c.doc_id = d.id
    WHERE c.kb_id = ? AND (${conditions})
    LIMIT ?
  `).all(kbId, ...params, limit) as unknown as Array<{ chunk_id: string; doc_id: string; kb_id: string; content: string; metadata_json: string | null; doc_name: string; doc_path: string; doc_extension: string | null }>

  const results: SearchResult[] = rows.map(row => {
    const contentLower = row.content.toLowerCase()
    let score = 0
    for (const term of terms) {
      const idx = contentLower.indexOf(term)
      if (idx >= 0) {
        score += 1.0 / (1.0 + idx * 0.001)
        const count = (contentLower.match(new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')) || []).length
        score += count * 0.1
      }
    }
    return {
      chunk_id: row.chunk_id,
      doc_id: row.doc_id,
      kb_id: row.kb_id,
      content: row.content,
      metadata_json: row.metadata_json,
      vector_score: 0,
      bm25_score: score,
      hybrid_score: score,
      doc_name: row.doc_name,
      doc_path: row.doc_path,
      doc_extension: row.doc_extension
    }
  })

  results.sort((a, b) => b.bm25_score - a.bm25_score)
  return results.slice(0, limit)
}

// ==================== Stats ====================

export function getKBStats(kbId: string): KBStats {
  const db = getDatabase()
  const docStats = db.prepare(`
    SELECT COUNT(*) as total,
           SUM(CASE WHEN status = 'indexed' THEN 1 ELSE 0 END) as indexed,
           COALESCE(SUM(size), 0) as total_size
    FROM kb_documents WHERE kb_id = ?
  `).get(kbId) as { total: number; indexed: number; total_size: number }

  const chunkCount = db.prepare('SELECT COUNT(*) as cnt FROM kb_chunks WHERE kb_id = ?').get(kbId) as { cnt: number }

  return {
    totalDocs: docStats.total,
    indexedDocs: docStats.indexed,
    totalChunks: chunkCount.cnt,
    totalSize: docStats.total_size,
    indexedPercent: docStats.total > 0 ? Math.round((docStats.indexed / docStats.total) * 100) : 0
  }
}

export function updateKBStats(kbId: string): void {
  const stats = getKBStats(kbId)
  getDatabase().prepare('UPDATE knowledge_bases SET stats_json = ?, updated_at = ? WHERE id = ?')
    .run(JSON.stringify(stats), now(), kbId)
}

// ==================== Backup/Restore ====================

export interface KBBackup {
  version: 1
  exported_at: number
  kb: KBRow
  sources: KBSourceRow[]
  documents: KBDocumentRow[]
  chunks: Array<Omit<KBChunkRow, 'embedding'> & { embedding: number[] | null }>
}

export function exportKB(kbId: string): KBBackup {
  const kb = getKB(kbId)
  if (!kb) throw new Error('KB not found')

  const sources = listSources(kbId)
  const documents = listDocuments(kbId)
  const chunks = listChunksByKB(kbId)

  return {
    version: 1,
    exported_at: now(),
    kb,
    sources,
    documents,
    chunks: chunks.map(c => ({
      ...c,
      embedding: c.embedding ? Array.from(bufferToVector(c.embedding as unknown as Buffer)) : null
    }))
  }
}

export function importKB(backup: KBBackup): string {
  const db = getDatabase()
  const ts = now()
  const newKbId = `kb-${nanoid(10)}`

  db.prepare('INSERT INTO knowledge_bases (id, name, description, config_json, stats_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)')
    .run(newKbId, backup.kb.name, backup.kb.description, backup.kb.config_json, backup.kb.stats_json, ts, ts)

  const sourceIdMap = new Map<string, string>()
  for (const src of backup.sources) {
    const newId = `src-${nanoid(10)}`
    sourceIdMap.set(src.id, newId)
    db.prepare('INSERT INTO kb_sources (id, kb_id, path, type, status, file_count, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)')
      .run(newId, newKbId, src.path, src.type, src.status, src.file_count, ts)
  }

  const docIdMap = new Map<string, string>()
  for (const doc of backup.documents) {
    const newId = `doc-${nanoid(10)}`
    docIdMap.set(doc.id, newId)
    const newSourceId = doc.source_id ? sourceIdMap.get(doc.source_id) || null : null
    db.prepare('INSERT INTO kb_documents (id, kb_id, source_id, path, name, extension, size, content_preview, chunk_count, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)')
      .run(newId, newKbId, newSourceId, doc.path, doc.name, doc.extension, doc.size, doc.content_preview, doc.chunk_count, doc.status, ts)
  }

  for (const chunk of backup.chunks) {
    const newId = `chk-${nanoid(10)}`
    const newDocId = docIdMap.get(chunk.doc_id)
    if (!newDocId) continue
    const embBuf = chunk.embedding ? vectorToBuffer(new Float32Array(chunk.embedding)) : null
    db.prepare('INSERT INTO kb_chunks (id, doc_id, kb_id, chunk_index, content, embedding, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)')
      .run(newId, newDocId, newKbId, chunk.chunk_index, chunk.content, embBuf, chunk.metadata_json, ts)
  }

  return newKbId
}
