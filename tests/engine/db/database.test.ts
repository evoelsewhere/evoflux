import { describe, it, expect, beforeAll } from 'vitest'
import { openDatabase, getDatabase } from '../../../src/engine/db/database'
import { saveWorkflow, getWorkflow, listWorkflows, deleteWorkflow } from '../../../src/engine/db/workflow-repo'
import { createRun, updateRunStatus, getRun, listRuns, createNodeRun, updateNodeRunStatus, getNodeRuns } from '../../../src/engine/db/run-repo'
import { setEnvVariable, getEnvVariable, listEnvVariables, deleteEnvVariable, getEnvVariablesMap } from '../../../src/engine/db/env-repo'

const dsl = (name: string) => ({
  name,
  version: '2.0' as const,
  description: '',
  graph: { nodes: [], edges: [] },
  config: {},
  metadata: { created_at: '', updated_at: '', tags: [] as string[] }
})

beforeAll(() => {
  openDatabase(':memory:')
})

describe('Database', () => {
  it('should initialize database', () => {
    expect(getDatabase()).toBeDefined()
  })
})

describe('WorkflowRepository', () => {
  it('should save and get workflow', () => {
    const saved = saveWorkflow(dsl('Test Workflow'))
    expect(saved.id).toBeTruthy()
    expect(saved.name).toBe('Test Workflow')
    const loaded = getWorkflow(saved.id)
    expect(loaded).not.toBeNull()
    expect(loaded!.name).toBe('Test Workflow')
  })

  it('should list workflows', () => {
    saveWorkflow(dsl('W1'))
    saveWorkflow(dsl('W2'))
    expect(listWorkflows().length).toBeGreaterThanOrEqual(2)
  })

  it('should update workflow', () => {
    const saved = saveWorkflow(dsl('Original'))
    const updated = dsl('Updated')
    ;(updated.metadata as Record<string, unknown>).template = saved.id
    saveWorkflow(updated)
    expect(getWorkflow(saved.id)!.name).toBe('Updated')
  })

  it('should delete workflow', () => {
    const saved = saveWorkflow(dsl('To Delete'))
    expect(deleteWorkflow(saved.id)).toBe(true)
    expect(getWorkflow(saved.id)).toBeNull()
  })
})

describe('RunRepository', () => {
  it('should create and get run', () => {
    const wf = saveWorkflow(dsl('W'))
    const run = createRun(wf.id, { input: 'test' })
    expect(run.id).toBeTruthy()
    expect(run.status).toBe('running')
    expect(getRun(run.id)).not.toBeNull()
  })

  it('should update run status', () => {
    const wf = saveWorkflow(dsl('W'))
    const run = createRun(wf.id)
    updateRunStatus(run.id, 'completed', { result: 'done' })
    const loaded = getRun(run.id)
    expect(loaded!.status).toBe('completed')
    expect(loaded!.finished_at).toBeTruthy()
  })

  it('should list runs', () => {
    const wf = saveWorkflow(dsl('W'))
    createRun(wf.id)
    createRun(wf.id)
    expect(listRuns(wf.id).length).toBeGreaterThanOrEqual(2)
  })

  it('should create and update node runs', () => {
    const wf = saveWorkflow(dsl('W'))
    const run = createRun(wf.id)
    const nodeRun = createNodeRun(run.id, 'node-1', 'llm', { prompt: 'test' })
    expect(nodeRun.status).toBe('running')
    updateNodeRunStatus(nodeRun.id, 'completed', { output: 'result' })
    const nodeRuns = getNodeRuns(run.id)
    expect(nodeRuns).toHaveLength(1)
    expect(nodeRuns[0].status).toBe('completed')
  })
})

describe('EnvVariables', () => {
  it('should set and get env variable', () => {
    setEnvVariable('wf-1', 'API_KEY', 'sk-123', true)
    expect(getEnvVariable('wf-1', 'API_KEY')).toBe('sk-123')
  })

  it('should update existing variable', () => {
    setEnvVariable('wf-2', 'KEY', 'old')
    setEnvVariable('wf-2', 'KEY', 'new')
    expect(getEnvVariable('wf-2', 'KEY')).toBe('new')
  })

  it('should list variables with masked secrets', () => {
    setEnvVariable('wf-3', 'SECRET', 'hidden', true)
    setEnvVariable('wf-3', 'NORMAL', 'visible', false)
    const list = listEnvVariables('wf-3')
    expect(list.find(v => v.key === 'SECRET')!.value).toBe('***')
    expect(list.find(v => v.key === 'NORMAL')!.value).toBe('visible')
  })

  it('should delete variable', () => {
    setEnvVariable('wf-4', 'DEL', 'val')
    expect(deleteEnvVariable('wf-4', 'DEL')).toBe(true)
    expect(getEnvVariable('wf-4', 'DEL')).toBeNull()
  })

  it('should get variables map', () => {
    setEnvVariable('wf-5', 'A', '1')
    setEnvVariable('wf-5', 'B', '2')
    const map = getEnvVariablesMap('wf-5')
    expect(map.A).toBe('1')
    expect(map.B).toBe('2')
  })
})
