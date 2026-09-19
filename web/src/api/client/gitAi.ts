import type { GitAIRequest, GitAIResponse } from '../types'
import { apiUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'
import { stripExtendedPathPrefix } from '@/lib/workspace-path-utils'

export async function runGitAIAction(
  workspace: string,
  request: GitAIRequest,
): Promise<GitAIResponse> {
  const params = new URLSearchParams({ workspace: stripExtendedPathPrefix(workspace) })
  const res = await fetch(apiUrl(`/team/workspace/git/ai?${params}`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(request),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'runGitAIAction')
  return res.json()
}
