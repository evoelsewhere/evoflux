import { nanoid } from 'nanoid'
import { getDatabase } from './database'
import { vectorToBuffer, bufferToVector, cosineSimilarity } from '../memory/embedding'

// Semantic
export function saveSemantic(workflowId: string, id: string, type: string, content: string, embedding?: Float32Array, metadata?: Record<string, unknown>): void {
  const db = getDatabase()
  const embeddingBuf = embedding ? vectorToBuffer(embedding) : null
  const metadataJson = metadata ? JSON.stringify(metadata) : null
  db.prepare('INSERT OR REPLACE INTO memory_semantic (id, workflow_id, type, content, embedding, metadata_json, created_at, access_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)')
    .run(id, workflowId, type, content, embeddingBuf, metadataJson, Date.now(), 0)
}

export function getSemantic(workflowId: string, id: string): Record<string, unknown> | null {
  const db = getDatabase()
  const row = db.prepare('SELECT * FROM memory_semantic WHERE id = ? AND workflow_id = ?').get(id, workflowId) as Record<string, unknown> | undefined
  if (!row) return null
  if (row.embedding) row.embedding = bufferToVector(row.embedding as Buffer)
  return row
}

export function searchSemanticByVector(workflowId: string, queryEmbedding: Float32Array, k = 5): Array<{ id: string; content: string; score: number }> {
  const db = getDatabase()
  const rows = db.prepare('SELECT id, content, embedding FROM memory_semantic WHERE workflow_id = ? AND embedding IS NOT NULL').all(workflowId) as Array<{ id: string; content: string; embedding: Buffer }>

  const scored = rows.map(row => {
    const vec = bufferToVector(row.embedding)
    const score = cosineSimilarity(queryEmbedding, vec)
    return { id: row.id, content: row.content, score }
  })

  scored.sort((a, b) => b.score - a.score)
  return scored.slice(0, k)
}

export function incrementSemanticAccess(id: string): void {
  const db = getDatabase()
  db.prepare('UPDATE memory_semantic SET access_count = access_count + 1 WHERE id = ?').run(id)
}

// Episodic
export function saveEpisodic(workflowId: string, id: string, runId: string, taskDescription: string, trajectory: unknown[], outcome: string, feedback: string, embedding?: Float32Array): void {
  const db = getDatabase()
  const embeddingBuf = embedding ? vectorToBuffer(embedding) : null
  db.prepare('INSERT OR REPLACE INTO memory_episodic (id, workflow_id, run_id, task_description, trajectory_json, outcome, feedback, embedding, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)')
    .run(id, workflowId, runId, taskDescription, JSON.stringify(trajectory), outcome, feedback, embeddingBuf, Date.now())
}

export function searchEpisodicByVector(workflowId: string, queryEmbedding: Float32Array, k = 5): Array<{ id: string; task_description: string; outcome: string; score: number }> {
  const db = getDatabase()
  const rows = db.prepare('SELECT id, task_description, outcome, embedding FROM memory_episodic WHERE workflow_id = ? AND embedding IS NOT NULL').all(workflowId) as Array<{ id: string; task_description: string; outcome: string; embedding: Buffer }>

  const scored = rows.map(row => {
    const vec = bufferToVector(row.embedding)
    const score = cosineSimilarity(queryEmbedding, vec)
    return { id: row.id, task_description: row.task_description, outcome: row.outcome, score }
  })

  scored.sort((a, b) => b.score - a.score)
  return scored.slice(0, k)
}

// Procedural
export function saveProcedural(workflowId: string, id: string, name: string, description: string, pattern: string, sourceEpisodes: string[], usageCount: number, successRate: number, maturityScore: number, embedding?: Float32Array): void {
  const db = getDatabase()
  const embeddingBuf = embedding ? vectorToBuffer(embedding) : null
  db.prepare('INSERT OR REPLACE INTO memory_procedural (id, workflow_id, name, description, pattern, source_episodes_json, usage_count, success_rate, maturity_score, embedding, created_at, last_used_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)')
    .run(id, workflowId, name, description, pattern, JSON.stringify(sourceEpisodes), usageCount, successRate, maturityScore, embeddingBuf, Date.now(), Date.now())
}

export function searchProceduralByVector(workflowId: string, queryEmbedding: Float32Array, k = 5): Array<{ id: string; name: string; pattern: string; score: number }> {
  const db = getDatabase()
  const rows = db.prepare('SELECT id, name, pattern, embedding FROM memory_procedural WHERE workflow_id = ? AND embedding IS NOT NULL').all(workflowId) as Array<{ id: string; name: string; pattern: string; embedding: Buffer }>

  const scored = rows.map(row => {
    const vec = bufferToVector(row.embedding)
    const score = cosineSimilarity(queryEmbedding, vec)
    return { id: row.id, name: row.name, pattern: row.pattern, score }
  })

  scored.sort((a, b) => b.score - a.score)
  return scored.slice(0, k)
}

// Edges
export function saveEdge(workflowId: string, sourceId: string, targetId: string, type: string, weight: number): string {
  const db = getDatabase()
  const id = nanoid(10)
  db.prepare('INSERT OR REPLACE INTO memory_edges (id, workflow_id, source_id, target_id, type, weight, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)')
    .run(id, workflowId, sourceId, targetId, type, weight, Date.now())
  return id
}

export function getEdgesFrom(workflowId: string, sourceId: string): Array<{ id: string; target_id: string; type: string; weight: number }> {
  const db = getDatabase()
  return db.prepare('SELECT id, target_id, type, weight FROM memory_edges WHERE workflow_id = ? AND source_id = ?').all(workflowId, sourceId) as Array<{ id: string; target_id: string; type: string; weight: number }>
}
