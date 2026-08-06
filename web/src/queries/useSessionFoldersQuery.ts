import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createSessionFolder,
  deleteSessionFolder,
  listSessionFolderSessions,
  listSessionFolders,
  setSessionFolder,
  updateSessionFolder,
} from '@/api/client'
import type { SessionFolderListResponse, SessionResponse } from '@/api/types'
import { queryKeys } from './keys'
import { patchSessionInPageData } from './session-cache'

type FolderMode = 'work' | 'coding'

/** Folders for one mode, each carrying its newest sessions inline. */
export function useSessionFoldersQuery(mode: FolderMode = 'work', enabled = true) {
  return useQuery({
    queryKey: queryKeys.team.sessionFolders(mode),
    queryFn: () => listSessionFolders(mode),
    enabled,
  })
}

export function useCreateSessionFolderMutation(mode: FolderMode = 'work') {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => createSessionFolder({ name, mode }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessionFolders(mode) })
    },
  })
}

export function useUpdateSessionFolderMutation(mode: FolderMode = 'work') {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      ...body
    }: { id: string; name?: string; share_context?: boolean; sort_order?: number }) =>
      updateSessionFolder(id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessionFolders(mode) })
    },
  })
}

export function useDeleteSessionFolderMutation(mode: FolderMode = 'work') {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteSessionFolder,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessionFolders(mode) })
      // Deleting a folder un-files its sessions, so they reappear in the
      // ungrouped list — that list is paginated server-side, hence a refetch
      // rather than a local splice.
      void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessions.all() })
    },
  })
}

/** Append the next cursor page to one expanded folder. */
export function useLoadMoreFolderSessionsMutation(mode: FolderMode = 'work') {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ folderId, before }: { folderId: string; before: string }) =>
      listSessionFolderSessions(folderId, before),
    onSuccess: (page, { folderId }) => {
      queryClient.setQueryData<SessionFolderListResponse>(
        queryKeys.team.sessionFolders(mode),
        (old) => {
          if (!old) return old
          return {
            folders: old.folders.map((folder) => {
              if (folder.id !== folderId) return folder
              const seen = new Set(folder.sessions.map((session) => session.id))
              return {
                ...folder,
                sessions: [
                  ...folder.sessions,
                  ...page.data.filter((session) => !seen.has(session.id)),
                ],
                next_cursor: page.next_cursor,
                has_more: page.has_more,
              }
            }),
          }
        },
      )
    },
  })
}

/**
 * Move a session into a folder (or out of every folder with `folderId: null`).
 *
 * Applies the new `folder_id` to the cached session lists right away so the
 * dragged row lands in its target group before the refetch settles; the
 * folders entry is then invalidated because a move changes two folders'
 * contents at once.
 */
export function useSetSessionFolderMutation(mode: FolderMode = 'work') {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      sessionId,
      folderId,
    }: {
      sessionId: string
      folderId: string | null
      /** The dragged row, so a session coming from the ungrouped list can be
       *  rendered in its new folder before the refetch returns. */
      session?: SessionResponse
    }) => setSessionFolder(sessionId, folderId),
    onMutate: async ({ sessionId, folderId, session }) => {
      await Promise.all([
        queryClient.cancelQueries({ queryKey: queryKeys.team.sessionFolders(mode) }),
        queryClient.cancelQueries({ queryKey: queryKeys.team.sessions.all() }),
      ])
      const previousFolders = queryClient.getQueryData<SessionFolderListResponse>(
        queryKeys.team.sessionFolders(mode),
      )
      const previousSessionQueries = queryClient.getQueriesData({
        queryKey: queryKeys.team.sessions.all(),
      })
      let moved = session
      queryClient.setQueryData<SessionFolderListResponse>(
        queryKeys.team.sessionFolders(mode),
        (old) => {
          if (!old) return old
          for (const folder of old.folders) {
            const match = folder.sessions.find((s) => s.id === sessionId)
            if (match) moved = match
          }
          return {
            folders: old.folders.map((folder) => {
              const without = folder.sessions.filter((s) => s.id !== sessionId)
              const isTarget = folder.id === folderId
              const sessions =
                isTarget && moved
                  ? [{ ...moved, folder_id: folderId }, ...without]
                  : without
              return {
                ...folder,
                sessions,
                session_count: Math.max(
                  0,
                  folder.session_count + (sessions.length - folder.sessions.length),
                ),
              }
            }),
          }
        },
      )
      if (moved) {
        const optimistic = { ...moved, folder_id: folderId }
        queryClient.setQueriesData({ queryKey: queryKeys.team.sessions.all() }, (old) =>
          patchSessionInPageData(old, optimistic),
        )
      }
      return { previousFolders, previousSessionQueries }
    },
    onError: (_error, _variables, context) => {
      if (!context) return
      queryClient.setQueryData(
        queryKeys.team.sessionFolders(mode),
        context.previousFolders,
      )
      for (const [key, data] of context.previousSessionQueries) {
        queryClient.setQueryData(key, data)
      }
    },
    onSuccess: (updated) => {
      queryClient.setQueriesData({ queryKey: queryKeys.team.sessions.all() }, (old) =>
        patchSessionInPageData(old, updated),
      )
      queryClient.setQueryData(
        queryKeys.team.sessions.detail(updated.id),
        (old: SessionResponse | undefined) => (old ? { ...old, ...updated } : old),
      )
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessionFolders(mode) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessions.all() })
    },
  })
}
