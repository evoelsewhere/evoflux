import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { dismissProblem, getProblems, suppressProblem } from '@/api/client'
import { queryKeys } from './keys'

export function useProblemsQuery(
  workspace: string,
  enabled: boolean,
  includeResolved = false,
) {
  return useQuery({
    queryKey: queryKeys.coding.problems(workspace, includeResolved),
    queryFn: () => getProblems(workspace, includeResolved),
    enabled: enabled && Boolean(workspace),
    staleTime: 1_000,
    refetchInterval: enabled ? 3_000 : false,
  })
}

export function useProblemDecisionMutation(workspace: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'dismiss' | 'suppress' }) =>
      action === 'dismiss' ? dismissProblem(workspace, id) : suppressProblem(workspace, id),
    onSuccess: () => queryClient.invalidateQueries({
      queryKey: ['coding-workspace-problems', workspace],
    }),
  })
}
