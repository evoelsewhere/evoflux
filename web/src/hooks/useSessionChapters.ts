import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createSessionChapter,
  deleteSessionChapter,
  listSessionChapters,
} from '@/api/client/team'
import { queryKeys } from '@/queries'
import type { Chapter } from '@/api/types'

export function useSessionChapters(sessionId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.chapters.list(sessionId ?? ''),
    queryFn: () => listSessionChapters(sessionId!),
    enabled: !!sessionId,
    staleTime: 30_000,
  })
}

export function useCreateChapter(sessionId: string | null | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      title,
      summary,
      messageId,
    }: {
      title: string
      summary?: string | null
      messageId?: string | null
    }) => createSessionChapter(sessionId!, title, summary, messageId),
    onSuccess: (chapter: Chapter) => {
      qc.setQueryData<Chapter[]>(
        queryKeys.chapters.list(sessionId ?? ''),
        (prev) => [...(prev ?? []), chapter],
      )
    },
  })
}

export function useDeleteChapter(sessionId: string | null | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (chapterId: string) => deleteSessionChapter(sessionId!, chapterId),
    onSuccess: (_data, chapterId) => {
      qc.setQueryData<Chapter[]>(
        queryKeys.chapters.list(sessionId ?? ''),
        (prev) => (prev ?? []).filter((c) => c.id !== chapterId),
      )
    },
  })
}
