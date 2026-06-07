import { ipcMain } from 'electron'
import { getOrCreateMemory } from '../../src/engine/nodes/knowledge-retrieval'

export function registerMemoryHandlers(): void {
  ipcMain.handle('memory:search', async (_event, workflowId, query, options) => {
    try {
      const memory = getOrCreateMemory(workflowId)
      const k = options?.k || 5
      const layer = options?.layer || 'all'

      const results: unknown[] = []

      if (layer === 'all' || layer === 'semantic') {
        const semantic = await memory.searchSemantic(query, k)
        results.push(...semantic.map(r => ({ type: 'semantic', ...r })))
      }

      if (layer === 'all' || layer === 'episodic') {
        const episodic = await memory.searchEpisodic(query, k)
        results.push(...episodic.map(r => ({ type: 'episodic', ...r })))
      }

      if (layer === 'all' || layer === 'procedural') {
        const procedural = await memory.searchProcedural(query, k)
        results.push(...procedural.map(r => ({ type: 'procedural', ...r })))
      }

      return { success: true, results }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Search failed'
      return { success: false, error: message }
    }
  })

  ipcMain.handle('memory:addSemantic', async (_event, workflowId, content, type, metadata) => {
    try {
      const memory = getOrCreateMemory(workflowId)
      const id = await memory.addSemantic(content, type, metadata)
      return { success: true, id }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Add failed'
      return { success: false, error: message }
    }
  })

  ipcMain.handle('memory:recordOutcome', async (_event, workflowId, outcome, feedback) => {
    try {
      const memory = getOrCreateMemory(workflowId)
      const id = await memory.recordOutcome(outcome, feedback)
      return { success: true, id }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Record failed'
      return { success: false, error: message }
    }
  })

  ipcMain.handle('memory:stats', async (_event, workflowId) => {
    try {
      const memory = getOrCreateMemory(workflowId)
      return { success: true, stats: memory.getStats() }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Stats failed'
      return { success: false, error: message }
    }
  })

  ipcMain.handle('memory:consolidate', async (_event, workflowId) => {
    try {
      const memory = getOrCreateMemory(workflowId)
      const result = await memory.consolidate()
      return { success: true, result }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Consolidate failed'
      return { success: false, error: message }
    }
  })
}
