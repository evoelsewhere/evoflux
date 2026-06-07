import { useCallback } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import type { WorkflowData } from '../types/workflow'

export function useWorkflow() {
  const store = useWorkflowStore()

  const saveWorkflow = useCallback(async () => {
    const workflow = {
      id: store.workflowId || undefined,
      name: store.workflowName,
      description: store.workflowDescription,
      nodes: store.nodes,
      edges: store.edges
    }

    const saved = (await window.api.workflow.save(workflow)) as WorkflowData
    store.setWorkflowId(saved.id)
    return saved
  }, [store])

  const loadWorkflow = useCallback(
    async (id: string) => {
      const workflow = (await window.api.workflow.load(id)) as WorkflowData | null
      if (workflow) {
        store.loadWorkflow(
          workflow.id,
          workflow.name,
          workflow.description,
          workflow.nodes,
          workflow.edges
        )
      }
      return workflow
    },
    [store]
  )

  const listWorkflows = useCallback(async () => {
    return (await window.api.workflow.list()) as WorkflowData[]
  }, [])

  const deleteWorkflow = useCallback(async (id: string) => {
    return await window.api.workflow.delete(id)
  }, [])

  return {
    saveWorkflow,
    loadWorkflow,
    listWorkflows,
    deleteWorkflow
  }
}
