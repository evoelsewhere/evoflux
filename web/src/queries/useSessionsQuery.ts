import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listTeamSessions, deleteTeamSession, duplicateTeamSession, updateTeamSessionTitle } from '@/api/client'
import type { SessionPageResponse, SessionResponse } from '@/api/types'
import { queryKeys } from './keys'
import { forgetSessionSnapshot } from '@/stores/useTeamStore'
import { patchSessionInPageData } from './session-cache'

const WORK_PAGE_SIZE = 40
const DEFAULT_PAGE_SIZE = 20
const CODING_WORKSPACE_PAGE_SIZE = 5
const CODING_WORKSPACE_SMOOTHING_MS = 5000

/** Paged session list, server-filtered by mode. Pass the surface's own
 * mode ('work' for the work sidebar, 'coding' for the coding sidebar) —
 * without the filter, coding sessions would mix into the work list and
 * pagination pages fill with rows the caller immediately drops. */
export function useTeamSessionsQuery(mode: 'work' | 'coding' = 'work') {
  return useInfiniteQuery({
    queryKey: queryKeys.team.sessions.infinite(mode),
    queryFn: ({ pageParam, signal }: { pageParam: string | null; signal: AbortSignal }) =>
      listTeamSessions(pageParam, mode === 'work' ? WORK_PAGE_SIZE : DEFAULT_PAGE_SIZE, { mode }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage: SessionPageResponse) =>
      lastPage.has_more ? lastPage.next_cursor : undefined,
  })
}

export function useCodingWorkspaceSessionsQuery(workspace: string, enabled = true) {
  return useInfiniteQuery({
    queryKey: queryKeys.team.sessions.workspace(workspace),
    queryFn: ({ pageParam, signal }: { pageParam: string | null; signal: AbortSignal }) =>
      listTeamSessions(pageParam, CODING_WORKSPACE_PAGE_SIZE, { mode: 'coding', workspace }, signal),
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
    queryFn: ({ pageParam, signal }: { pageParam: string | null; signal: AbortSignal }) =>
      listTeamSessions(pageParam, CODING_WORKSPACE_PAGE_SIZE, { mode: 'coding', project_id: projectId }, signal),
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
      queryClient.setQueryData(queryKeys.team.sessions.metadata(updated.id), (old: SessionResponse | undefined) => old ? { ...old, ...updated } : old)
    },
  })
}

export function useDeleteTeamSessionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteTeamSession,
    onSuccess: (_data, sessionId) => {
      // The store keeps recently visited sessions in memory so returning
      // to one paints instantly. A deleted session must not be one of
      // them, or reopening its id would show a transcript that is gone.
      forgetSessionSnapshot(sessionId)
      queryClient.invalidateQueries({ queryKey: queryKeys.team.sessions.all() })
      // A deleted session may have been filed in a sidebar folder, whose
      // sessions live in their own cache entry.
      queryClient.invalidateQueries({ queryKey: queryKeys.team.sessionFoldersAll() })
    },
  })
}

export function useDuplicateTeamSessionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: duplicateTeamSession,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.team.sessions.all() })
      queryClient.invalidateQueries({ queryKey: queryKeys.team.sessionFoldersAll() })
    },
  })
}
