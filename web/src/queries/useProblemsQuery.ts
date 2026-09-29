import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { dismissProblem, getProblems, restoreProblem, suppressProblem } from '@/api/client'
import type { ProblemDecision } from '@/api/types'
import { useToastStore } from '@/stores/useToastStore'
import { queryKeys } from './keys'

/** Problems of every repository the session works in, primary first. */
export function useProblemsQuery(
  workspaces: readonly string[],
  enabled: boolean,
  includeResolved = false,
) {
  return useQuery({
    queryKey: queryKeys.coding.problems(workspaces, includeResolved),
    queryFn: () => getProblems(workspaces, includeResolved),
    enabled: enabled && workspaces.length > 0,
    staleTime: 1_000,
    refetchInterval: enabled ? 3_000 : false,
  })
}

export function useProblemDecisionMutation() {
  const queryClient = useQueryClient()
  const pushToast = useToastStore((state) => state.push)
  return useMutation({
    // A decision goes to the repository the row came from, which is not the
    // primary for a finding in one of the project's other repositories.
    mutationFn: ({ id, action, workspace }: { id: string; action: ProblemDecision; workspace: string }) => {
      if (action === 'dismiss') return dismissProblem(workspace, id)
      if (action === 'suppress') return suppressProblem(workspace, id)
      return restoreProblem(workspace, id)
    },
    onSuccess: () => queryClient.invalidateQueries({
      queryKey: ['coding-workspace-problems'],
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
