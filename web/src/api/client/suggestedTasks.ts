import { apiBaseUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'
import type { SuggestedTask, SuggestedTaskStartResult } from '../types'

export async function getSuggestedTasks(
  sessionId: string,
  options: { includeResolved?: boolean } = {},
): Promise<SuggestedTask[]> {
  const query = options.includeResolved ? '?include_resolved=true' : ''
  const res = await fetch(
    `${apiBaseUrl()}/team/sessions/${encodeURIComponent(sessionId)}/suggested-tasks${query}`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'getSuggestedTasks')
  return (await res.json()).tasks
}

/**
 * Turn a chip into its own session.
 *
 * The prompt comes back rather than being sent, so the caller posts it through
 * the ordinary chat path once it has navigated to the new session.
 */
export async function startSuggestedTask(
  taskId: string,
  options: { isolated?: boolean } = {},
): Promise<SuggestedTaskStartResult> {
  const res = await fetch(
    `${apiBaseUrl()}/team/suggested-tasks/${encodeURIComponent(taskId)}/start`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ isolated: options.isolated ?? false }),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'startSuggestedTask')
  return res.json()
}

export async function dismissSuggestedTask(
  taskId: string,
  reason?: string,
): Promise<SuggestedTask> {
  const res = await fetch(
    `${apiBaseUrl()}/team/suggested-tasks/${encodeURIComponent(taskId)}/dismiss`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: reason ?? null }),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'dismissSuggestedTask')
  return res.json()
}
