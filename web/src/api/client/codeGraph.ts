/**
 * Client for the code knowledge graph API (``/api/code-graph``). Every
 * endpoint is scoped to a coding-workspace directory via the ``workspace``
 * query param; the panel uses these to show index status, run hybrid
 * (lexical + semantic) symbol search, and trigger a re-index.
 */

import { apiBaseUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'
import type {
  CodeGraphReindexResponse,
  CodeGraphSearchResponse,
  CodeGraphStatusResponse,
} from '../types'

export async function getCodeGraphStatus(
  workspace: string,
): Promise<CodeGraphStatusResponse> {
  const params = new URLSearchParams({ workspace })
  const res = await fetch(`${apiBaseUrl()}/code-graph/status?${params}`, {
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) await parseDetailOrThrow(res, 'getCodeGraphStatus')
  return res.json()
}

export async function searchCodeGraph(
  workspace: string,
  query: string,
  options?: { kind?: string; limit?: number },
): Promise<CodeGraphSearchResponse> {
  const params = new URLSearchParams({ workspace, query })
  if (options?.kind) params.set('kind', options.kind)
  if (options?.limit) params.set('limit', String(options.limit))
  const res = await fetch(`${apiBaseUrl()}/code-graph/search?${params}`, {
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) await parseDetailOrThrow(res, 'searchCodeGraph')
  return res.json()
}

export async function reindexCodeGraph(
  workspace: string,
  options?: { full?: boolean },
): Promise<CodeGraphReindexResponse> {
  const params = new URLSearchParams({ workspace })
  const res = await fetch(`${apiBaseUrl()}/code-graph/reindex?${params}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ full: options?.full ?? false }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'reindexCodeGraph')
  return res.json()
}
