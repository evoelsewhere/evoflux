import { useQuery } from '@tanstack/react-query'
import { listWorkflows } from '@/api/client'

export function useWorkflowsQuery(workspace?: string | null) {
  return useQuery({
    queryKey: ['workflows', 'list', workspace ?? null],
    queryFn: () => listWorkflows(workspace),
    staleTime: 15_000,
  })
}
