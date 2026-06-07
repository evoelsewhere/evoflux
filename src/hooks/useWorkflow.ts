import { useCallback } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import type { WorkflowData } from '../types/workflow'

export function useWorkflow() {
  const workflowId = useWorkflowStore(s => s.workflowId)
  const workflowName = useWorkflowStore(s => s.workflowName)
  const workflowDescription = useWorkflowStore(s => s.workflowDescription)
  const nodes = useWorkflowStore(s => s.nodes)
  const edges = useWorkflowStore(s => s.edges)
  const setWorkflowId = useWorkflowStore(s => s.setWorkflowId)
  const loadWorkflow = useWorkflowStore(s => s.loadWorkflow)

  const saveWorkflow = useCallback(async () => {
    const workflow = {
      id: workflowId || undefined,
      name: workflowName,
      description: workflowDescription,
      nodes,
      edges
    }

    const saved = (await window.api.workflow.save(workflow)) as WorkflowData
    setWorkflowId(saved.id)
    return saved
  }, [workflowId, workflowName, workflowDescription, nodes, edges, setWorkflowId])

  const loadWorkflowById = useCallback(
    async (id: string) => {
      const workflow = (await window.api.workflow.load(id)) as WorkflowData | null
      if (workflow) {
        loadWorkflow(
          workflow.id,
          workflow.name,
          workflow.description,
          workflow.nodes,
          workflow.edges
        )
      }
      return workflow
    },
    [loadWorkflow]
  )

  const listWorkflows = useCallback(async () => {
    return (await window.api.workflow.list()) as WorkflowData[]
  }, [])

  const deleteWorkflow = useCallback(async (id: string) => {
    return await window.api.workflow.delete(id)
  }, [])

  return {
    saveWorkflow,
    loadWorkflow: loadWorkflowById,
    listWorkflows,
    deleteWorkflow
  }
}
