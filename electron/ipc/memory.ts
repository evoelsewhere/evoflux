import { ipcMain } from 'electron'
import { embed } from '../../src/engine/memory/embedding'
import {
  saveSemantic,
  searchSemanticByVector,
  searchEpisodicByVector,
  searchProceduralByVector,
  incrementSemanticAccess
} from '../../src/engine/db/memory-repo'
import { getMemoryStats } from '../../src/engine/db/repos'

export function registerMemoryHandlers(): void {
  ipcMain.handle('memory:search', async (_event, workflowId: string, query: string, options?: { k?: number; layer?: string }) => {
    try {
      const k = options?.k || 5
      const layer = options?.layer || 'all'
      const queryEmbedding = await embed(query, 'query')

      const results: Array<{ type: string; id: string; content: string; score: number }> = []

      if (layer === 'all' || layer === 'semantic') {
        const semantic = searchSemanticByVector(workflowId, queryEmbedding, k)
        results.push(...semantic.map(r => ({ type: 'semantic', ...r })))
        for (const r of semantic) incrementSemanticAccess(r.id)
      }

      if (layer === 'all' || layer === 'episodic') {
        const episodic = searchEpisodicByVector(workflowId, queryEmbedding, k)
        results.push(...episodic.map(r => ({ type: 'episodic', id: r.id, content: `[${r.outcome}] ${r.task_description}`, score: r.score })))
      }

      if (layer === 'all' || layer === 'procedural') {
        const procedural = searchProceduralByVector(workflowId, queryEmbedding, k)
        results.push(...procedural.map(r => ({ type: 'procedural', id: r.id, content: `${r.name}: ${r.pattern}`, score: r.score })))
      }

      results.sort((a, b) => b.score - a.score)
      return { success: true, results: results.slice(0, k) }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Search failed'
      return { success: false, error: message }
    }
  })

  ipcMain.handle('memory:addSemantic', async (_event, workflowId: string, content: string, type: string, metadata?: Record<string, unknown>) => {
    try {
      const embedding = await embed(content, 'passage')
      const id = `mem-${Date.now()}`
      saveSemantic(workflowId, id, type, content, embedding, metadata)
      return { success: true, id }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Add failed'
      return { success: false, error: message }
    }
  })

  ipcMain.handle('memory:stats', async (_event, workflowId: string) => {
    try {
      const stats = getMemoryStats(workflowId)
      return { success: true, stats }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Stats failed'
      return { success: false, error: message }
    }
  })
}
