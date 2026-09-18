import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { dismissProblem, getProblems, restoreProblem, suppressProblem } from '@/api/client'
import type { ProblemDecision } from '@/api/types'
import { useToastStore } from '@/stores/useToastStore'
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
  const pushToast = useToastStore((state) => state.push)
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: ProblemDecision }) => {
      if (action === 'dismiss') return dismissProblem(workspace, id)
      if (action === 'suppress') return suppressProblem(workspace, id)
      return restoreProblem(workspace, id)
    },
    onSuccess: () => queryClient.invalidateQueries({
      queryKey: ['coding-workspace-problems', workspace],
    }),
    // A decision that did not take used to fail in silence: the row stayed,
    // the poll put it back, and the user pressed the button again.
    onError: (error, { action }) => pushToast({
      tone: 'error',
      title: `Could not ${action}`,
      description: error instanceof Error ? error.message : undefined,
    }),
  })
}
