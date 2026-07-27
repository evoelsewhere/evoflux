import { apiBaseUrl } from '../base-url'
import { withTokenParam } from '../auth'
import { parseDetailOrThrow } from './_shared'
import type {
  CodeReviewsResponse,
  CodeReviewActionInput,
  CodeReviewContext,
  GitServerConnection,
  GitServerConnectionInput,
} from '../types'

export interface CodeReviewScope {
  workspace?: string | null
  projectId?: string | null
}

export function getCodeReviewImageUrl(
  workspaceId: string,
  sourceUrl: string,
): string {
  try {
    const parsed = new URL(sourceUrl)
    const isAttachment =
      ['http:', 'https:'].includes(parsed.protocol) &&
      /^\/user-attachments\/assets\/[0-9a-f-]+\/?$/i.test(parsed.pathname)
    const isRenderedImage =
      ['private-user-images.githubusercontent.com', 'user-images.githubusercontent.com'].includes(parsed.hostname) &&
      /^\/[0-9]+\/[0-9]+-[0-9a-f-]+(?:\.[a-z0-9]+)?$/i.test(parsed.pathname)
    if (!isAttachment && !isRenderedImage) return sourceUrl
  } catch {
    return sourceUrl
  }
  const params = new URLSearchParams({ url: sourceUrl })
  return withTokenParam(
    `${apiBaseUrl()}/team/reviews/${encodeURIComponent(workspaceId)}/media?${params.toString()}`,
  )
}

export async function getCodeReviews(
  scope: CodeReviewScope = {},
): Promise<CodeReviewsResponse> {
  const params = new URLSearchParams()
  if (scope.projectId) params.set('project_id', scope.projectId)
  else if (scope.workspace) params.set('workspace', scope.workspace)
  const query = params.size > 0 ? `?${params.toString()}` : ''
  const res = await fetch(`${apiBaseUrl()}/team/reviews${query}`)
  if (!res.ok) await parseDetailOrThrow(res, 'getCodeReviews')
  return res.json()
}

export async function getCodeReview(
  workspaceId: string,
  number: number,
): Promise<CodeReviewContext> {
  const res = await fetch(
    `${apiBaseUrl()}/team/reviews/${encodeURIComponent(workspaceId)}/${number}`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'getCodeReview')
  return res.json()
}

export async function mutateCodeReview(
  workspaceId: string,
  number: number,
  body: CodeReviewActionInput,
): Promise<Record<string, unknown>> {
  const res = await fetch(
    `${apiBaseUrl()}/team/reviews/${encodeURIComponent(workspaceId)}/${number}/actions`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'mutateCodeReview')
  return res.json()
}

export async function getGitServerConnections(): Promise<GitServerConnection[]> {
  const res = await fetch(`${apiBaseUrl()}/team/reviews/connections`)
  if (!res.ok) await parseDetailOrThrow(res, 'getGitServerConnections')
  return res.json()
}

export async function createGitServerConnection(
  body: GitServerConnectionInput,
): Promise<GitServerConnection> {
  const res = await fetch(`${apiBaseUrl()}/team/reviews/connections`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'createGitServerConnection')
  return res.json()
}

export async function updateGitServerConnection(
  id: string,
  body: Partial<GitServerConnectionInput>,
): Promise<GitServerConnection> {
  const res = await fetch(
    `${apiBaseUrl()}/team/reviews/connections/${encodeURIComponent(id)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'updateGitServerConnection')
  return res.json()
}

export async function deleteGitServerConnection(id: string): Promise<void> {
  const res = await fetch(
    `${apiBaseUrl()}/team/reviews/connections/${encodeURIComponent(id)}`,
    { method: 'DELETE' },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'deleteGitServerConnection')
}

export async function testGitServerConnection(body: {
  provider: GitServerConnectionInput['provider']
  domain: string
  token: string
  username?: string | null
  verify_ssl: boolean
}): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/reviews/connections/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'testGitServerConnection')
}
