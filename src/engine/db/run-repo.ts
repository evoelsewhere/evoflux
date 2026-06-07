import { nanoid } from 'nanoid'
import { getDatabase } from './database'

export interface RunRecord {
  id: string
  workflow_id: string
  status: 'running' | 'completed' | 'failed' | 'aborted'
  input_json: string | null
  output_json: string | null
  started_at: number
  finished_at: number | null
}

export interface NodeRunRecord {
  id: string
  run_id: string
  node_id: string
  node_type: string
  status: 'running' | 'completed' | 'error'
  input_json: string | null
  output_json: string | null
  error: string | null
  started_at: number
  finished_at: number | null
}

export function createRun(workflowId: string, input?: unknown): RunRecord {
  const db = getDatabase()
  const id = nanoid(10)
  const now = Date.now()
  const inputJson = input ? JSON.stringify(input) : null

  db.prepare('INSERT OR REPLACE INTO runs (id, workflow_id, status, input_json, started_at) VALUES (?, ?, ?, ?, ?)')
    .run(id, workflowId, 'running', inputJson, now)

  return { id, workflow_id: workflowId, status: 'running', input_json: inputJson, output_json: null, started_at: now, finished_at: null }
}

export function updateRunStatus(id: string, status: RunRecord['status'], output?: unknown): void {
  const db = getDatabase()
  const now = Date.now()
  const outputJson = output ? JSON.stringify(output) : null

  if (status === 'completed' || status === 'failed' || status === 'aborted') {
    db.prepare('UPDATE runs SET status = ?, output_json = ?, finished_at = ? WHERE id = ?')
      .run(status, outputJson, now, id)
  } else {
    db.prepare('UPDATE runs SET status = ? WHERE id = ?')
      .run(status, id)
  }
}

export function getRun(id: string): RunRecord | null {
  const db = getDatabase()
  const row = db.prepare('SELECT * FROM runs WHERE id = ?').get(id) as RunRecord | undefined
  return row || null
}

export function listRuns(workflowId: string): RunRecord[] {
  const db = getDatabase()
  return db.prepare('SELECT * FROM runs WHERE workflow_id = ? ORDER BY started_at DESC').all(workflowId) as unknown as RunRecord[]
}

export function createNodeRun(runId: string, nodeId: string, nodeType: string, input?: unknown): NodeRunRecord {
  const db = getDatabase()
  const id = nanoid(10)
  const now = Date.now()
  const inputJson = input ? JSON.stringify(input) : null

  db.prepare('INSERT OR REPLACE INTO node_runs (id, run_id, node_id, node_type, status, input_json, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)')
    .run(id, runId, nodeId, nodeType, 'running', inputJson, now)

  return { id, run_id: runId, node_id: nodeId, node_type: nodeType, status: 'running', input_json: inputJson, output_json: null, error: null, started_at: now, finished_at: null }
}

export function updateNodeRunStatus(id: string, status: NodeRunRecord['status'], output?: unknown, error?: string): void {
  const db = getDatabase()
  const now = Date.now()
  const outputJson = output ? JSON.stringify(output) : null

  db.prepare('UPDATE node_runs SET status = ?, output_json = ?, error = ?, finished_at = ? WHERE id = ?')
    .run(status, outputJson, error || null, now, id)
}

export function getNodeRuns(runId: string): NodeRunRecord[] {
  const db = getDatabase()
  return db.prepare('SELECT * FROM node_runs WHERE run_id = ? ORDER BY started_at ASC').all(runId) as unknown as NodeRunRecord[]
}
