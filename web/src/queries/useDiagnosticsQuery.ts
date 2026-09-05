import { useMutation, useQueryClient, useQuery } from '@tanstack/react-query'
import { getDiagnostics, runDiagnosticsAction } from '@/api/client'
import { queryKeys } from './keys'

export function useDiagnosticsQuery() {
  return useQuery({
    queryKey: queryKeys.diagnostics(),
    queryFn: getDiagnostics,
    staleTime: 0,      // always re-fetch on mount
    gcTime: 60_000,
    retry: 1,
  })
}

/**
 * Run a check's own fix, then re-read the checks.
 *
 * The result is only trustworthy after a fresh read — the point of the
 * button is that the row it sits in changes.
 */
export function useDiagnosticsActionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (actionId: string) => runDiagnosticsAction(actionId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.diagnostics() }),
  })
}
