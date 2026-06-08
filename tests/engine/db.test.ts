import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { join } from 'path'
import { tmpdir } from 'os'
import { mkdtemp, rm } from 'fs/promises'
import { openDatabase, closeDatabase, getDatabase } from '../../src/engine/db/database'
import {
  saveWorkflow, getWorkflow, listWorkflows, deleteWorkflow,
  setSetting, getSetting, getSettingsJson, getAllSettings,
  saveProvider, getProvider, listProviders, updateProvider, deleteProvider, clearDefaultProviders,
  createRun, updateRunStatus, getRun, listRuns
} from '../../src/engine/db/repos'

let dbDir: string

describe('Database', () => {
  beforeAll(async () => {
    dbDir = await mkdtemp(join(tmpdir(), 'evolux-db-test-'))
    openDatabase(join(dbDir, 'test.db'))
  })

  afterAll(async () => {
    closeDatabase()
    await rm(dbDir, { recursive: true, force: true })
  })

  describe('Settings', () => {
    it('should set and get a setting', () => {
      setSetting('theme', 'dark')
      expect(getSetting('theme')).toBe('"dark"')
    })

    it('should get settings as JSON', () => {
      setSetting('appearance', { theme: 'dark', fontSize: 13 })
      const result = getSettingsJson('appearance') as Record<string, unknown>
      expect(result.theme).toBe('dark')
      expect(result.fontSize).toBe(13)
    })

    it('should get all settings', () => {
      setSetting('key1', 'value1')
      setSetting('key2', { nested: true })
      const all = getAllSettings()
      expect(all.key1).toBe('value1')
      expect((all.key2 as Record<string, unknown>).nested).toBe(true)
    })

    it('should overwrite existing setting', () => {
      setSetting('overwrite', 'old')
      setSetting('overwrite', 'new')
      expect(getSetting('overwrite')).toBe('"new"')
    })

    it('should return null for missing key', () => {
      expect(getSetting('nonexistent')).toBeNull()
    })
  })

  describe('Providers', () => {
    afterAll(() => {
      const providers = listProviders()
      for (const p of providers) deleteProvider(p.id)
    })

    it('should save a provider', () => {
      const id = saveProvider({
        name: 'Test OpenAI',
        type: 'openai',
        api_key: 'sk-test',
        base_url: 'https://api.openai.com/v1',
        default_model: 'gpt-4o',
        models: ['gpt-4o', 'gpt-4o-mini'],
        is_default: true
      })
      expect(id).toBeTruthy()

      const p = getProvider(id)
      expect(p).toBeDefined()
      expect(p!.name).toBe('Test OpenAI')
      expect(p!.type).toBe('openai')
      expect(p!.api_key).toBe('sk-test')
      expect(JSON.parse(p!.models_json)).toEqual(['gpt-4o', 'gpt-4o-mini'])
      expect(p!.is_default).toBe(1)
    })

    it('should save Anthropic provider with custom URL', () => {
      const id = saveProvider({
        name: 'Test Anthropic',
        type: 'anthropic',
        api_key: 'test-key',
        base_url: 'https://custom.anthropic.com',
        default_model: 'claude-sonnet-4-20250514',
        models: ['claude-sonnet-4-20250514', 'claude-3-haiku-20240307']
      })
      expect(id).toBeTruthy()

      const p = getProvider(id)
      expect(p!.base_url).toBe('https://custom.anthropic.com')
    })

    it('should list providers ordered by default then name', () => {
      clearDefaultProviders()
      saveProvider({ name: 'B Provider', type: 'openai' })
      saveProvider({ name: 'A Provider', type: 'openai', is_default: true })
      saveProvider({ name: 'C Provider', type: 'ollama' })

      const list = listProviders()
      expect(list.length).toBeGreaterThanOrEqual(3)
      expect(list[0].is_default).toBe(1)
    })

    it('should update provider fields', () => {
      const id = saveProvider({ name: 'ToUpdate', type: 'openai' })
      updateProvider(id, { name: 'Updated', api_key: 'new-key', default_model: 'gpt-4o' })

      const p = getProvider(id)
      expect(p!.name).toBe('Updated')
      expect(p!.api_key).toBe('new-key')
      expect(p!.default_model).toBe('gpt-4o')
    })

    it('should delete provider', () => {
      const id = saveProvider({ name: 'ToDelete', type: 'openai' })
      deleteProvider(id)
      expect(getProvider(id)).toBeUndefined()
    })

    it('should clear default flag on all providers', () => {
      saveProvider({ name: 'Default1', type: 'openai', is_default: true })
      saveProvider({ name: 'Default2', type: 'openai', is_default: true })
      clearDefaultProviders()
      const list = listProviders()
      for (const p of list) {
        expect(p.is_default).toBe(0)
      }
    })
  })

  describe('Workflows', () => {
    it('should save a workflow with nodes and edges', () => {
      const nodes = [
        { id: 'start-1', type: 'manual-trigger', data: { label: 'Start', type: 'manual-trigger' }, position: { x: 0, y: 0 } },
        { id: 'llm-1', type: 'llm', data: { label: 'LLM', type: 'llm', config: { model: 'gpt-4o', prompt: 'Hello' } }, position: { x: 0, y: 100 } }
      ]
      const edges = [
        { id: 'e1', source: 'start-1', target: 'llm-1' }
      ]

      const saved = saveWorkflow({
        id: 'test-wf-1',
        name: 'Test Workflow',
        description: 'A test workflow',
        nodes,
        edges
      })

      expect(saved.id).toBe('test-wf-1')
      expect(saved.name).toBe('Test Workflow')
    })

    it('should load workflow with correct nodes and edges', () => {
      const wf = getWorkflow('test-wf-1')
      expect(wf).toBeDefined()

      const loadedNodes = JSON.parse(wf!.nodes_json)
      const loadedEdges = JSON.parse(wf!.edges_json)

      expect(loadedNodes).toHaveLength(2)
      expect(loadedNodes[0].id).toBe('start-1')
      expect(loadedNodes[1].id).toBe('llm-1')
      expect(loadedNodes[1].data.config.model).toBe('gpt-4o')

      expect(loadedEdges).toHaveLength(1)
      expect(loadedEdges[0].source).toBe('start-1')
      expect(loadedEdges[0].target).toBe('llm-1')
    })

    it('should update workflow on re-save', () => {
      const nodes = [{ id: 'start-1', type: 'manual-trigger', data: { label: 'Start' } }]
      saveWorkflow({ id: 'test-wf-update', name: 'Original', nodes, edges: [] })

      const updatedNodes = [...nodes, { id: 'llm-1', type: 'llm', data: { label: 'New LLM' } }]
      saveWorkflow({ id: 'test-wf-update', name: 'Updated', nodes: updatedNodes, edges: [] })

      const wf = getWorkflow('test-wf-update')
      expect(wf!.name).toBe('Updated')
      expect(JSON.parse(wf!.nodes_json)).toHaveLength(2)
    })

    it('should list workflows', () => {
      saveWorkflow({ id: 'wf-list-1', name: 'List1', nodes: [], edges: [] })
      saveWorkflow({ id: 'wf-list-2', name: 'List2', nodes: [], edges: [] })

      const list = listWorkflows()
      expect(list.length).toBeGreaterThanOrEqual(2)
      const names = list.map(w => w.name)
      expect(names).toContain('List1')
      expect(names).toContain('List2')
    })

    it('should delete workflow', () => {
      saveWorkflow({ id: 'wf-del', name: 'ToDelete', nodes: [], edges: [] })
      deleteWorkflow('wf-del')
      expect(getWorkflow('wf-del')).toBeUndefined()
    })

    it('should persist complex node config', () => {
      const nodes = [{
        id: 'code-1',
        type: 'code',
        data: {
          label: 'Code',
          type: 'code',
          config: {
            language: 'python',
            code: 'def hello():\n    return "world"'
          }
        }
      }]
      saveWorkflow({ id: 'wf-complex', name: 'Complex', nodes, edges: [] })

      const wf = getWorkflow('wf-complex')
      const loaded = JSON.parse(wf!.nodes_json)
      expect(loaded[0].data.config.code).toContain('def hello')
    })

    it('should persist edge conditions and back-edge flags', () => {
      const edges = [
        { id: 'e1', source: 'a', target: 'b', condition: 'output.result === true', isBackEdge: false },
        { id: 'e2', source: 'b', target: 'a', isBackEdge: true, maxIterations: 50 }
      ]
      saveWorkflow({ id: 'wf-edges', name: 'Edges', nodes: [], edges })

      const wf = getWorkflow('wf-edges')
      const loaded = JSON.parse(wf!.edges_json)
      expect(loaded[0].condition).toBe('output.result === true')
      expect(loaded[1].isBackEdge).toBe(true)
      expect(loaded[1].maxIterations).toBe(50)
    })
  })

  describe('Runs', () => {
    beforeAll(() => {
      saveWorkflow({ id: 'wf-run-test', name: 'Run Test', nodes: [], edges: [] })
    })

    it('should create a run', () => {
      const runId = createRun('wf-run-test', { input: 'test' })
      expect(runId).toBeTruthy()
      expect(runId).toMatch(/^run-/)
    })

    it('should update run status', () => {
      const runId = createRun('wf-run-test')
      updateRunStatus(runId, 'completed', { result: 'success' })

      const run = getRun(runId)
      expect(run!.status).toBe('completed')
      expect(JSON.parse(run!.output_json!)).toEqual({ result: 'success' })
    })

    it('should list runs for a workflow', () => {
      createRun('wf-run-test')
      createRun('wf-run-test')
      const runs = listRuns('wf-run-test')
      expect(runs.length).toBeGreaterThanOrEqual(2)
    })

    it('should handle run with error status', () => {
      const runId = createRun('wf-run-test')
      updateRunStatus(runId, 'error', { error: 'Something failed' })

      const run = getRun(runId)
      expect(run!.status).toBe('error')
    })
  })
})
