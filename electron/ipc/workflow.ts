import { ipcMain } from 'electron'
import { saveWorkflow, getWorkflow, listWorkflows, deleteWorkflow, createRun, updateRunStatus, listRuns, createNodeRun, updateNodeRunStatus } from '../../src/engine/db/repos'

export function registerWorkflowHandlers(): void {
  ipcMain.handle('workflow:save', async (_event, workflow) => {
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
  })

  ipcMain.handle('workflow:load', async (_event, id: string) => {
    const wf = getWorkflow(id)
    if (!wf) return null
    return {
      id: wf.id, name: wf.name, description: wf.description,
      nodes: JSON.parse(wf.nodes_json), edges: JSON.parse(wf.edges_json),
      createdAt: new Date(wf.created_at).toISOString(),
      updatedAt: new Date(wf.updated_at).toISOString()
    }
  })

  ipcMain.handle('workflow:list', async () => {
    const rows = listWorkflows()
    return rows.map(wf => ({
      id: wf.id, name: wf.name, description: wf.description,
      nodes: JSON.parse(wf.nodes_json), edges: JSON.parse(wf.edges_json),
      createdAt: new Date(wf.created_at).toISOString(),
      updatedAt: new Date(wf.updated_at).toISOString()
    }))
  })

  ipcMain.handle('workflow:delete', async (_event, id: string) => {
    deleteWorkflow(id)
    return true
  })

  ipcMain.handle('workflow:runs', async (_event, workflowId: string) => {
    return listRuns(workflowId)
  })
}
