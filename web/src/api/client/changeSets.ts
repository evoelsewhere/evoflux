import type { ChangeSetCreateRequest, ChangeSetResponse } from '../types'
import { apiUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'

function changeSetUrl(workspace: string, suffix = ''): string {
  const params = new URLSearchParams({ workspace })
  return apiUrl(`/team/workspace/change-sets${suffix}?${params}`)
}

export async function createChangeSet(
  workspace: string,
  request: ChangeSetCreateRequest,
): Promise<ChangeSetResponse> {
  const res = await fetch(changeSetUrl(workspace), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(request),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'createChangeSet')
  return res.json()
}

export async function getChangeSet(
  workspace: string,
  changeSetId: string,
): Promise<ChangeSetResponse> {
  const res = await fetch(changeSetUrl(workspace, `/${encodeURIComponent(changeSetId)}`))
  if (!res.ok) await parseDetailOrThrow(res, 'getChangeSet')
  return res.json()
}

async function decideChangeSet(
  workspace: string,
  changeSetId: string,
  decision: 'apply' | 'reject',
  paths?: string[],
  sessionId?: string | null,
): Promise<ChangeSetResponse> {
  const suffix = `/${encodeURIComponent(changeSetId)}/${decision}`
  const res = await fetch(changeSetUrl(workspace, suffix), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ paths, session_id: sessionId ?? undefined }),
  })
  if (!res.ok) await parseDetailOrThrow(res, `${decision}ChangeSet`)
  return res.json()
}

export function applyChangeSet(
  workspace: string,
  changeSetId: string,
  paths?: string[],
  sessionId?: string | null,
): Promise<ChangeSetResponse> {
  return decideChangeSet(workspace, changeSetId, 'apply', paths, sessionId)
}

export function rejectChangeSet(
  workspace: string,
  changeSetId: string,
  paths?: string[],
): Promise<ChangeSetResponse> {
  return decideChangeSet(workspace, changeSetId, 'reject', paths)
}
