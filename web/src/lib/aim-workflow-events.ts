export function workflowProgressExecutionId(type: string, data: unknown): string | null {
  if (type !== 'workflow_progress' || typeof data !== 'object' || data === null) return null
  const executionId = (data as Record<string, unknown>).execution_id
  return typeof executionId === 'string' && executionId.length > 0 ? executionId : null
}
