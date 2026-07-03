import type { SessionResponse } from '@/api/types'

export function patchSessionInPageData(old: unknown, updated: SessionResponse): unknown {
  if (!old || typeof old !== 'object' || !('pages' in old) || !Array.isArray(old.pages)) return old
  return {
    ...old,
    pages: old.pages.map((page) => ({
      ...page,
      data: page.data.map((session: SessionResponse) => session.id === updated.id ? updated : session),
    })),
  }
}
