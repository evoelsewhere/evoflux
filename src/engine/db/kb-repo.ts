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

export function searchChunksByVector(kbId: string, queryEmbedding: number[], limit: number = 10): SearchResult[] {
  const db = getDatabase()
  type JoinedChunk = KBChunkRow & { doc_name: string; doc_path: string; doc_extension: string | null }
  const rows = db.prepare(`
    SELECT c.id as chunk_id, c.doc_id, c.kb_id, c.content, c.metadata_json, c.embedding,
           d.name as doc_name, d.path as doc_path, d.extension as doc_extension
    FROM kb_chunks c
    JOIN kb_documents d ON c.doc_id = d.id
    WHERE c.kb_id = ? AND c.embedding IS NOT NULL
  `).all(kbId) as unknown as JoinedChunk[]

  const queryVec = new Float32Array(queryEmbedding)
  const results: SearchResult[] = []
  for (const row of rows) {
    const chunkVec = bufferToVector(row.embedding! as unknown as Buffer)
    const score = cosineSimilarity(queryVec, chunkVec)
    results.push({
      chunk_id: (row as unknown as { chunk_id: string }).chunk_id,
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
    })
  }

  results.sort((a, b) => b.vector_score - a.vector_score)
  return results.slice(0, limit)
}

// ==================== BM25 Search (FTS5) ====================

export function searchChunksByBM25(kbId: string, query: string, limit: number = 20): SearchResult[] {
  const db = getDatabase()

  const ftsRows = db.prepare(`
    SELECT rowid, rank FROM kb_chunks_fts
    WHERE kb_chunks_fts MATCH ?
    ORDER BY rank
    LIMIT ?
  `).all(query, limit) as unknown as Array<{ rowid: number; rank: number }>

  if (ftsRows.length === 0) return []

  const rowids = ftsRows.map(r => r.rowid)
  const placeholders = rowids.map(() => '?').join(',')
  const chunks = db.prepare(`
    SELECT c.rowid, c.id as chunk_id, c.doc_id, c.kb_id, c.content, c.metadata_json,
           d.name as doc_name, d.path as doc_path, d.extension as doc_extension
    FROM kb_chunks c
    JOIN kb_documents d ON c.doc_id = d.id
    WHERE c.rowid IN (${placeholders}) AND c.kb_id = ?
  `).all(...rowids, kbId) as unknown as Array<{ rowid: number; chunk_id: string; doc_id: string; kb_id: string; content: string; metadata_json: string | null; doc_name: string; doc_path: string; doc_extension: string | null }>

  const rankMap = new Map(ftsRows.map(r => [r.rowid, r.rank]))
  const results: SearchResult[] = chunks.map(row => ({
    chunk_id: row.chunk_id,
    doc_id: row.doc_id,
    kb_id: row.kb_id,
    content: row.content,
    metadata_json: row.metadata_json,
    vector_score: 0,
    bm25_score: rankMap.get(row.rowid) || 0,
    hybrid_score: rankMap.get(row.rowid) || 0,
    doc_name: row.doc_name,
    doc_path: row.doc_path,
    doc_extension: row.doc_extension
  }))

  results.sort((a, b) => b.bm25_score - a.bm25_score)
  return results
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
