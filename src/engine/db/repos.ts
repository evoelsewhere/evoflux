import { getDatabase } from './database'
import { nanoid } from 'nanoid'

function now(): number { return Date.now() }

// ==================== Settings ====================

export function getSetting(key: string): string | null {
  const row = getDatabase().prepare('SELECT value FROM settings WHERE key = ?').get(key)
  return row ? String(row.value) : null
}

export function setSetting(key: string, value: unknown): void {
  getDatabase().prepare('INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)').run(key, JSON.stringify(value), now())
}

export function getSettingsJson(key: string): unknown {
  const raw = getSetting(key)
  if (!raw) return null
  try { return JSON.parse(raw) } catch { return raw }
}

export function getAllSettings(): Record<string, unknown> {
  const rows = getDatabase().prepare('SELECT key, value FROM settings').all()
  const result: Record<string, unknown> = {}
  for (const row of rows) {
    try { result[String(row.key)] = JSON.parse(String(row.value)) } catch { result[String(row.key)] = row.value }
  }
  return result
}

// ==================== Providers ====================

export interface ProviderRow {
  id: string
  name: string
  type: string
  api_key: string
  base_url: string
  default_model: string
  models_json: string
  is_default: number
  created_at: number
  updated_at: number
}

export function listProviders(): ProviderRow[] {
  return getDatabase().prepare('SELECT * FROM providers ORDER BY is_default DESC, name ASC').all() as unknown as ProviderRow[]
}

export function getProvider(id: string): ProviderRow | undefined {
  return getDatabase().prepare('SELECT * FROM providers WHERE id = ?').get(id) as ProviderRow | undefined
}

export function saveProvider(p: { id?: string; name: string; type: string; api_key?: string; base_url?: string; default_model?: string; models?: string[]; is_default?: boolean }): string {
  const id = p.id || `prov-${nanoid(8)}`
  const ts = now()
  getDatabase().prepare(`INSERT OR REPLACE INTO providers (id, name, type, api_key, base_url, default_model, models_json, is_default, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(
    id, p.name, p.type, p.api_key || '', p.base_url || '', p.default_model || '',
    JSON.stringify(p.models || []), p.is_default ? 1 : 0, ts, ts
  )
  return id
}

export function updateProvider(id: string, patch: Partial<{ name: string; api_key: string; base_url: string; default_model: string; models: string[]; is_default: boolean }>): void {
  const existing = getProvider(id)
  if (!existing) return
  const sets: string[] = []
  const vals: unknown[] = []
  if (patch.name !== undefined) { sets.push('name = ?'); vals.push(patch.name) }
  if (patch.api_key !== undefined) { sets.push('api_key = ?'); vals.push(patch.api_key) }
  if (patch.base_url !== undefined) { sets.push('base_url = ?'); vals.push(patch.base_url) }
  if (patch.default_model !== undefined) { sets.push('default_model = ?'); vals.push(patch.default_model) }
  if (patch.models !== undefined) { sets.push('models_json = ?'); vals.push(JSON.stringify(patch.models)) }
  if (patch.is_default !== undefined) { sets.push('is_default = ?'); vals.push(patch.is_default ? 1 : 0) }
  if (sets.length === 0) return
  sets.push('updated_at = ?'); vals.push(now())
  vals.push(id)
  getDatabase().prepare(`UPDATE providers SET ${sets.join(', ')} WHERE id = ?`).run(...vals)
}

export function deleteProvider(id: string): void {
  getDatabase().prepare('DELETE FROM providers WHERE id = ?').run(id)
}

export function clearDefaultProviders(): void {
  getDatabase().prepare('UPDATE providers SET is_default = 0').run()
}

// ==================== Workflows ====================

export interface WorkflowRow {
  id: string
  name: string
  description: string
  nodes_json: string
  edges_json: string
  created_at: number
  updated_at: number
}

export function listWorkflows(): WorkflowRow[] {
  return getDatabase().prepare('SELECT * FROM workflows ORDER BY updated_at DESC').all() as unknown as WorkflowRow[]
}

export function getWorkflow(id: string): WorkflowRow | undefined {
  return getDatabase().prepare('SELECT * FROM workflows WHERE id = ?').get(id) as WorkflowRow | undefined
}

export function saveWorkflow(wf: { id?: string; name: string; description?: string; nodes: unknown; edges: unknown }): WorkflowRow {
  const id = wf.id || `wf-${nanoid(10)}`
  const ts = now()
  const existing = getWorkflow(id)
  const createdAt = existing?.created_at || ts
  getDatabase().prepare(`INSERT OR REPLACE INTO workflows (id, name, description, nodes_json, edges_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)`).run(
    id, wf.name, wf.description || '', JSON.stringify(wf.nodes), JSON.stringify(wf.edges), createdAt, ts
  )
  return { id, name: wf.name, description: wf.description || '', nodes_json: JSON.stringify(wf.nodes), edges_json: JSON.stringify(wf.edges), created_at: createdAt, updated_at: ts }
}

export function deleteWorkflow(id: string): void {
  getDatabase().prepare('DELETE FROM workflows WHERE id = ?').run(id)
}

// ==================== Runs ====================

export interface RunRow {
  id: string
  workflow_id: string
  status: string
  input_json: string | null
  output_json: string | null
  started_at: number
  finished_at: number | null
}

export function createRun(workflowId: string, input?: unknown): string {
  const id = `run-${nanoid(10)}`
  getDatabase().prepare('INSERT INTO runs (id, workflow_id, status, input_json, started_at) VALUES (?, ?, ?, ?, ?)').run(id, workflowId, 'running', input ? JSON.stringify(input) : null, now())
  return id
}

export function updateRunStatus(id: string, status: string, output?: unknown): void {
  getDatabase().prepare('UPDATE runs SET status = ?, output_json = ?, finished_at = ? WHERE id = ?').run(status, output ? JSON.stringify(output) : null, now(), id)
}

export function getRun(id: string): RunRow | undefined {
  return getDatabase().prepare('SELECT * FROM runs WHERE id = ?').get(id) as RunRow | undefined
}

export function listRuns(workflowId: string, limit = 20): RunRow[] {
  return getDatabase().prepare('SELECT * FROM runs WHERE workflow_id = ? ORDER BY started_at DESC LIMIT ?').all(workflowId, limit) as unknown as RunRow[]
}

// ==================== Node Runs ====================

export function createNodeRun(runId: string, nodeId: string, nodeType: string): string {
  const id = `nr-${nanoid(10)}`
  getDatabase().prepare('INSERT INTO node_runs (id, run_id, node_id, node_type, status, started_at) VALUES (?, ?, ?, ?, ?, ?)').run(id, runId, nodeId, nodeType, 'running', now())
  return id
}

export function updateNodeRunStatus(id: string, status: string, output?: unknown, error?: string): void {
  getDatabase().prepare('UPDATE node_runs SET status = ?, output_json = ?, error = ?, finished_at = ? WHERE id = ?').run(status, output ? JSON.stringify(output) : null, error || null, now(), id)
}

export function getNodeRuns(runId: string): Array<{ id: string; node_id: string; node_type: string; status: string; output_json: string | null; error: string | null }> {
  return getDatabase().prepare('SELECT * FROM node_runs WHERE run_id = ? ORDER BY started_at ASC').all(runId) as Array<{ id: string; node_id: string; node_type: string; status: string; output_json: string | null; error: string | null }>
}

// ==================== Memory ====================

export function addSemanticMemory(workflowId: string, type: string, content: string, metadata?: unknown): string {
  const id = `mem-${nanoid(10)}`
  getDatabase().prepare('INSERT INTO memory_semantic (id, workflow_id, type, content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?)').run(id, workflowId, type, content, metadata ? JSON.stringify(metadata) : null, now())
  return id
}

export function searchSemanticMemory(workflowId: string, query: string, limit = 10): Array<{ id: string; content: string; metadata_json: string | null }> {
  return getDatabase().prepare('SELECT id, content, metadata_json FROM memory_semantic WHERE workflow_id = ? AND content LIKE ? ORDER BY access_count DESC LIMIT ?').all(workflowId, `%${query}%`, limit) as Array<{ id: string; content: string; metadata_json: string | null }>
}

export function addEpisodicMemory(workflowId: string, runId: string, taskDescription: string, trajectory: string, outcome: string, feedback?: string): string {
  const id = `ep-${nanoid(10)}`
  getDatabase().prepare('INSERT INTO memory_episodic (id, workflow_id, run_id, task_description, trajectory_json, outcome, feedback, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)').run(id, workflowId, runId, taskDescription, trajectory, outcome, feedback || null, now())
  return id
}

export function getMemoryStats(workflowId: string): { semantic: number; episodic: number; procedural: number } {
  const semantic = Number(getDatabase().prepare('SELECT COUNT(*) as c FROM memory_semantic WHERE workflow_id = ?').get(workflowId)?.c || 0)
  const episodic = Number(getDatabase().prepare('SELECT COUNT(*) as c FROM memory_episodic WHERE workflow_id = ?').get(workflowId)?.c || 0)
  const procedural = Number(getDatabase().prepare('SELECT COUNT(*) as c FROM memory_procedural WHERE workflow_id = ?').get(workflowId)?.c || 0)
  return { semantic, episodic, procedural }
}

// ==================== Env Variables ====================

export function setEnvVariable(workflowId: string, key: string, value: string, isSecret = false): void {
  getDatabase().prepare('INSERT OR REPLACE INTO env_variables (id, workflow_id, key, value, is_secret) VALUES (?, ?, ?, ?, ?)').run(`env-${workflowId}-${key}`, workflowId, key, value, isSecret ? 1 : 0)
}

export function getEnvVariables(workflowId: string): Array<{ key: string; value: string; is_secret: number }> {
  return getDatabase().prepare('SELECT key, value, is_secret FROM env_variables WHERE workflow_id = ?').all(workflowId) as Array<{ key: string; value: string; is_secret: number }>
}

export function deleteEnvVariable(workflowId: string, key: string): void {
  getDatabase().prepare('DELETE FROM env_variables WHERE workflow_id = ? AND key = ?').run(workflowId, key)
}
