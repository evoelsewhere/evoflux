import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listTeamSessions, deleteTeamSession, updateTeamSessionTitle } from '@/api/client'
import type { SessionPageResponse, SessionResponse } from '@/api/types'
import { queryKeys } from './keys'
import { patchSessionInPageData } from './session-cache'

const PAGE_SIZE = 20
const CODING_WORKSPACE_PAGE_SIZE = 5
const CODING_WORKSPACE_SMOOTHING_MS = 5000

/** Paged session list, server-filtered by mode. Pass the surface's own
 * mode ('work' for the work sidebar, 'coding' for the coding sidebar) —
 * without the filter, per-run aim sessions flood the work list and
 * pagination pages fill with rows the caller immediately drops. */
export function useTeamSessionsQuery(mode: 'work' | 'coding' | 'aim' = 'work') {
  return useInfiniteQuery({
    queryKey: queryKeys.team.sessions.infinite(mode),
    queryFn: ({ pageParam }: { pageParam: string | null }) =>
      listTeamSessions(pageParam, PAGE_SIZE, { mode }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage: SessionPageResponse) =>
      lastPage.has_more ? lastPage.next_cursor : undefined,
  })
}

export function useCodingWorkspaceSessionsQuery(workspace: string, enabled = true) {
  return useInfiniteQuery({
    queryKey: queryKeys.team.sessions.workspace(workspace),
    queryFn: ({ pageParam }: { pageParam: string | null }) =>
      listTeamSessions(pageParam, CODING_WORKSPACE_PAGE_SIZE, { mode: 'coding', workspace }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage: SessionPageResponse) =>
      lastPage.has_more ? lastPage.next_cursor : undefined,
    enabled,
    staleTime: CODING_WORKSPACE_SMOOTHING_MS,
  })
}

export function useProjectSessionsQuery(projectId: string, enabled = true) {
  return useInfiniteQuery({
    queryKey: queryKeys.team.sessions.project(projectId),
    queryFn: ({ pageParam }: { pageParam: string | null }) =>
      listTeamSessions(pageParam, CODING_WORKSPACE_PAGE_SIZE, { mode: 'coding', project_id: projectId }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage: SessionPageResponse) =>
      lastPage.has_more ? lastPage.next_cursor : undefined,
    enabled,
    staleTime: CODING_WORKSPACE_SMOOTHING_MS,
  })
}

export function useUpdateTeamSessionTitleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => updateTeamSessionTitle(id, title),
    onSuccess: (updated) => {
      queryClient.setQueriesData({ queryKey: queryKeys.team.sessions.all() }, (old) => patchSessionInPageData(old, updated))
      queryClient.setQueryData(queryKeys.team.sessions.detail(updated.id), (old: SessionResponse | undefined) => old ? { ...old, ...updated } : old)
    },
  })
}

export function useDeleteTeamSessionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteTeamSession,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.team.sessions.all() })
    },
  })
}
