import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { changeDocumentVersion, getDocumentVersions, type DocumentVersionAction } from '@/api/client'
import { queryKeys } from './keys'

/**
 * Version history of one workspace document. ``revision`` (the file's mtime)
 * refetches it after every save, which is also what records that save when
 * nothing else did.
 */
export function useDocumentVersionsQuery(sessionId: string | undefined, path: string, revision: number) {
  return useQuery({
    queryKey: [...queryKeys.team.documentVersions(sessionId ?? '', path), revision],
    queryFn: () => getDocumentVersions(sessionId ?? '', path),
    enabled: Boolean(sessionId),
    staleTime: 5_000,
    placeholderData: (previous) => previous,
  })
}

export function useDocumentVersionMutation(sessionId: string | undefined, path: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (change: DocumentVersionAction) => changeDocumentVersion(sessionId ?? '', path, change),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.team.documentVersions(sessionId ?? '', path) })
      // The restored bytes land on disk; refresh the file list so the viewer re-renders.
      if (sessionId) void client.invalidateQueries({ queryKey: queryKeys.team.files(sessionId) })
    },
  })
}
