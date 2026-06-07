import { ipcMain } from 'electron'
import Store from 'electron-store'
import { nanoid } from 'nanoid'

interface Workflow {
  id: string
  name: string
  description: string
  nodes: unknown[]
  edges: unknown[]
  createdAt: string
  updatedAt: string
}

const store = new Store<{ workflows: Record<string, Workflow> }>({
  defaults: { workflows: {} }
})

export function registerWorkflowHandlers(): void {
  ipcMain.handle('workflow:save', async (_event, workflow: Partial<Workflow>) => {
    const workflows = store.get('workflows') || {}
    const id = workflow.id || nanoid()
    const now = new Date().toISOString()

    const savedWorkflow: Workflow = {
      id,
      name: workflow.name || 'Untitled Workflow',
      description: workflow.description ?? (workflows as Record<string, Workflow>)[id]?.description ?? '',
      nodes: workflow.nodes || [],
      edges: workflow.edges || [],
      createdAt: (workflows as Record<string, Workflow>)[id]?.createdAt || now,
      updatedAt: now
    }

    ;(workflows as Record<string, Workflow>)[id] = savedWorkflow
    store.set('workflows', workflows)

    return savedWorkflow
  })

  ipcMain.handle('workflow:load', async (_event, id: string) => {
    const workflows = store.get('workflows') || {}
    return (workflows as Record<string, Workflow>)[id] || null
  })

  ipcMain.handle('workflow:list', async () => {
    const workflows = store.get('workflows') || {}
    return Object.values(workflows as Record<string, Workflow>).sort(
      (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
    )
  })

  ipcMain.handle('workflow:delete', async (_event, id: string) => {
    const workflows = store.get('workflows') || {}
    delete (workflows as Record<string, Workflow>)[id]
    store.set('workflows', workflows)
    return true
  })
}
