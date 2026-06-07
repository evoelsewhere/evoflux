import { nanoid } from 'nanoid'
import { getDatabase } from './database'

export interface EnvVariable {
  id: string
  workflow_id: string
  key: string
  value: string
  is_secret: number
}

export function setEnvVariable(workflowId: string, key: string, value: string, isSecret = false): void {
  const db = getDatabase()
  const existing = db.prepare('SELECT id FROM env_variables WHERE workflow_id = ? AND key = ?').get(workflowId, key) as { id: string } | undefined

  if (existing) {
    db.prepare('UPDATE env_variables SET value = ?, is_secret = ? WHERE id = ?')
      .run(value, isSecret ? 1 : 0, existing.id)
  } else {
    db.prepare('INSERT INTO env_variables (id, workflow_id, key, value, is_secret) VALUES (?, ?, ?, ?, ?)')
      .run(nanoid(10), workflowId, key, value, isSecret ? 1 : 0)
  }
}

export function getEnvVariable(workflowId: string, key: string): string | null {
  const db = getDatabase()
  const row = db.prepare('SELECT value FROM env_variables WHERE workflow_id = ? AND key = ?').get(workflowId, key) as { value: string } | undefined
  return row?.value || null
}

export function listEnvVariables(workflowId: string): Array<{ key: string; value: string; is_secret: boolean }> {
  const db = getDatabase()
  const rows = db.prepare('SELECT key, value, is_secret FROM env_variables WHERE workflow_id = ?').all(workflowId) as Array<{ key: string; value: string; is_secret: number }>
  return rows.map(r => ({
    key: r.key,
    value: r.is_secret ? '***' : r.value,
    is_secret: Boolean(r.is_secret)
  }))
}

export function deleteEnvVariable(workflowId: string, key: string): boolean {
  const db = getDatabase()
  const result = db.prepare('DELETE FROM env_variables WHERE workflow_id = ? AND key = ?').run(workflowId, key)
  return result.changes > 0
}

export function getEnvVariablesMap(workflowId: string): Record<string, string> {
  const db = getDatabase()
  const rows = db.prepare('SELECT key, value FROM env_variables WHERE workflow_id = ?').all(workflowId) as Array<{ key: string; value: string }>
  const map: Record<string, string> = {}
  for (const row of rows) {
    map[row.key] = row.value
  }
  return map
}
