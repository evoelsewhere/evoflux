/**
 * The completed-turn file summary ("Edited N files"), from the live
 * ``turn_changes`` event or from the copy saved on the turn's user message.
 */
import type { MessageResponse, TurnChangedFile, TurnChangesPending } from '@/api/types'

/** Key of the saved summary in a user message's ``extra``. */
export const TURN_CHANGES_EXTRA_KEY = 'turn_changes'

/** A summary with no files is no summary: ``null`` clears the card. */
export function parseTurnChanges(
  sessionId: string,
  data: Record<string, unknown> | null | undefined,
): TurnChangesPending | null {
  if (!data) return null
  const filesRaw = Array.isArray(data.files) ? data.files : []
  const files: TurnChangedFile[] = []
  for (const f of filesRaw) {
    if (!f || typeof f !== 'object') continue
    const row = f as Record<string, unknown>
    const path = typeof row.path === 'string' ? row.path : null
    if (!path) continue
    const statusRaw = row.status
    const status: TurnChangedFile['status'] =
      statusRaw === 'added' ||
      statusRaw === 'modified' ||
      statusRaw === 'removed' ||
      statusRaw === 'changed'
        ? statusRaw
        : 'changed'
    files.push({
      path,
      status,
      additions: typeof row.additions === 'number' ? row.additions : null,
      deletions: typeof row.deletions === 'number' ? row.deletions : null,
    })
  }
  if (files.length === 0) return null
  return {
    sessionId: (typeof data.session_id === 'string' && data.session_id) || sessionId,
    additions: typeof data.additions === 'number' ? data.additions : 0,
    deletions: typeof data.deletions === 'number' ? data.deletions : 0,
    files,
  }
}

/**
 * The latest turn's summary as saved in history.
 *
 * Only the last user message counts: an earlier turn's summary describes
 * changes the newer turn may have superseded, and a turn that changed
 * nothing has none. *messages* must already exclude a reverted suffix.
 */
export function turnChangesFromHistory(
  sessionId: string,
  messages: readonly MessageResponse[],
): TurnChangesPending | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const msg = messages[index]
    if (msg.role !== 'user') continue
    // A queued message has not started its turn, and an agent's hand-off
    // is not the user's turn.
    if (msg.extra?.queue_status === 'queued' || msg.extra?.from_agent) continue
    const saved = msg.extra?.[TURN_CHANGES_EXTRA_KEY]
    return parseTurnChanges(sessionId, saved && typeof saved === 'object' ? saved as Record<string, unknown> : null)
  }
  return null
}
