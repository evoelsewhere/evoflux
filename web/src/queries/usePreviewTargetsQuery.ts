import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getPreviewTargets,
  startPreviewTarget,
  stopPreviewTarget,
} from '@/api/client'
import { queryKeys } from './keys'

/**
 * Dev servers declared in the workspace's launch.json, joined with the live
 * state of their ports. Polled while visible so a server the agent starts (or
 * one the user starts in a terminal) shows up without a manual refresh.
 */
export function usePreviewTargetsQuery(workspace: string | null, enabled = true) {
  const active = Boolean(workspace) && enabled
  return useQuery({
    queryKey: queryKeys.coding.preview(workspace ?? ''),
    queryFn: ({ signal }) => getPreviewTargets(workspace as string, signal),
    enabled: active,
    refetchInterval: active ? 3_000 : false,
  })
}

export function usePreviewStartMutation(workspace: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => startPreviewTarget(workspace as string, name),
    onSettled: () => queryClient.invalidateQueries({
      queryKey: queryKeys.coding.preview(workspace ?? ''),
    }),
  })
}

export function usePreviewStopMutation(workspace: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => stopPreviewTarget(workspace as string, name),
    onSettled: () => queryClient.invalidateQueries({
      queryKey: queryKeys.coding.preview(workspace ?? ''),
    }),
  })
}
