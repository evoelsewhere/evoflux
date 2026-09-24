import { apiUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'

export interface DocumentVersion {
  id: string
  size: number
  /** Seconds since the epoch. */
  created_at: number
  label: string
  source: 'baseline' | 'checkpoint' | 'change' | string
}

export interface DocumentHistory {
  path: string
  head: string | null
  can_undo: boolean
  can_redo: boolean
  versions: DocumentVersion[]
}

export type DocumentVersionAction =
  | { action: 'checkpoint'; label?: string }
  | { action: 'restore'; version_id: string }
  | { action: 'undo' }
  | { action: 'redo' }

function versionsUrl(sessionId: string): string {
  return apiUrl(`/team/${encodeURIComponent(sessionId)}/document-versions`)
}

/** A workspace document's versions; also records a change made unwatched. */
export async function getDocumentVersions(sessionId: string, path: string): Promise<DocumentHistory> {
  const res = await fetch(`${versionsUrl(sessionId)}?${new URLSearchParams({ path })}`, {
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) await parseDetailOrThrow(res, 'getDocumentVersions')
  return res.json()
}

/** Checkpoint, restore, undo or redo; the workspace file changes accordingly. */
export async function changeDocumentVersion(
  sessionId: string,
  path: string,
  change: DocumentVersionAction,
): Promise<DocumentHistory> {
  const res = await fetch(versionsUrl(sessionId), {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, ...change }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'changeDocumentVersion')
  return res.json()
}
