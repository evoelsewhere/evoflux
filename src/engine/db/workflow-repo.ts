import { nanoid } from 'nanoid'
import { getDatabase } from './database'
import type { WorkflowDSL } from '../dsl'

export interface WorkflowRecord {
  id: string
  name: string
  description: string
  dsl_json: string
  config_json: string | null
  created_at: number
  updated_at: number
}

export function saveWorkflow(workflow: Partial<WorkflowDSL> & { name: string }): WorkflowRecord {
  const db = getDatabase()
  const now = Date.now()
  const id = workflow.metadata?.template || nanoid(10)
  const dslJson = JSON.stringify(workflow)
  const configJson = workflow.config ? JSON.stringify(workflow.config) : null

  const existing = db.prepare('SELECT id FROM workflows WHERE id = ?').get(id) as { id: string } | undefined

  if (existing) {
    db.prepare('UPDATE workflows SET name = ?, description = ?, dsl_json = ?, config_json = ?, updated_at = ? WHERE id = ?')
      .run(workflow.name, workflow.description || '', dslJson, configJson, now, id)
  } else {
    db.prepare('INSERT OR REPLACE INTO workflows (id, name, description, dsl_json, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)')
      .run(id, workflow.name, workflow.description || '', dslJson, configJson, now, now)
  }

  return getWorkflow(id)!
}

export function getWorkflow(id: string): WorkflowRecord | null {
  const db = getDatabase()
  const row = db.prepare('SELECT * FROM workflows WHERE id = ?').get(id) as WorkflowRecord | undefined
  return row || null
}

export function listWorkflows(): WorkflowRecord[] {
  const db = getDatabase()
  return (db.prepare('SELECT * FROM workflows ORDER BY updated_at DESC').all() as unknown as WorkflowRecord[])
}

export function deleteWorkflow(id: string): boolean {
  const db = getDatabase()
  const result = db.prepare('DELETE FROM workflows WHERE id = ?').run(id)
  return result.changes > 0
}
