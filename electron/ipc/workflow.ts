import { ipcMain } from 'electron'
import { saveWorkflow, getWorkflow, listWorkflows, deleteWorkflow, listRuns } from '../../src/engine/db/repos'

export function registerWorkflowHandlers(): void {
  ipcMain.on('workflow:saveSync', (event, workflow) => {
    try {
      const saved = saveWorkflow({
        id: workflow.id,
        name: workflow.name || 'Untitled Workflow',
        description: workflow.description || '',
        nodes: workflow.nodes || [],
        edges: workflow.edges || []
      })
      event.returnValue = { success: true, id: saved.id }
    } catch (error) {
      event.returnValue = { success: false, error: error instanceof Error ? error.message : 'Save failed' }
    }
  })

  ipcMain.handle('workflow:save', async (_event, workflow) => {
    try {
      const saved = saveWorkflow({
        id: workflow.id,
        name: workflow.name || 'Untitled Workflow',
        description: workflow.description || '',
        nodes: workflow.nodes || [],
        edges: workflow.edges || []
      })
      return {
        id: saved.id, name: saved.name, description: saved.description,
        nodes: JSON.parse(saved.nodes_json), edges: JSON.parse(saved.edges_json),
        createdAt: new Date(saved.created_at).toISOString(),
        updatedAt: new Date(saved.updated_at).toISOString()
      }
    } catch (error) {
      throw new Error(`Failed to save workflow: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  })

  ipcMain.handle('workflow:load', async (_event, id: string) => {
    try {
      const wf = getWorkflow(id)
      if (!wf) return null
      return {
        id: wf.id, name: wf.name, description: wf.description,
        nodes: JSON.parse(wf.nodes_json), edges: JSON.parse(wf.edges_json),
        createdAt: new Date(wf.created_at).toISOString(),
        updatedAt: new Date(wf.updated_at).toISOString()
      }
    } catch (error) {
      throw new Error(`Failed to load workflow: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  })

  ipcMain.handle('workflow:list', async () => {
    try {
      const rows = listWorkflows()
      return rows.map(wf => ({
        id: wf.id, name: wf.name, description: wf.description,
        nodes: JSON.parse(wf.nodes_json), edges: JSON.parse(wf.edges_json),
        createdAt: new Date(wf.created_at).toISOString(),
        updatedAt: new Date(wf.updated_at).toISOString()
      }))
    } catch (error) {
      throw new Error(`Failed to list workflows: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  })

  ipcMain.handle('workflow:delete', async (_event, id: string) => {
    try {
      deleteWorkflow(id)
      return true
    } catch (error) {
      throw new Error(`Failed to delete workflow: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  })

  ipcMain.handle('workflow:runs', async (_event, workflowId: string) => {
    try {
      return listRuns(workflowId)
    } catch (error) {
      throw new Error(`Failed to list runs: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  })
}
