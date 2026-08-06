/**
 * Client for the code knowledge graph API (``/api/code-graph``). Every
 * endpoint is scoped to a coding-workspace directory via the ``workspace``
 * query param; the panel uses these to show index/freshness status, run
 * task-oriented graph + live-source retrieval, and trigger a re-index.
 */

import { apiBaseUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'
import type {
  CodeGraphFreshnessResponse,
  CodeGraphLanguageCapability,
  CodeGraphReindexResponse,
  CodeGraphSearchResponse,
  CodeGraphStatusResponse,
  CodeGraphFreshnessPolicy,
  CodeGraphNavigateResponse,
  CodeGraphOperation,
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

export async function navigateCodeGraph(
  workspace: string,
  symbol: string,
  options?: {
    operation?: CodeGraphOperation
    freshness?: CodeGraphFreshnessPolicy
    path?: string
    repository?: string
    depth?: number
    limit?: number
    signal?: AbortSignal
  },
): Promise<CodeGraphNavigateResponse> {
  const params = new URLSearchParams({ workspace })
  const res = await fetch(`${apiBaseUrl()}/code-graph/navigate?${params}`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({
      symbol,
      operation: options?.operation ?? 'definition',
      freshness: options?.freshness ?? 'balanced',
      path: options?.path ?? null,
      repository: options?.repository ?? null,
      depth: options?.depth ?? 1,
      limit: options?.limit ?? 40,
    }),
    signal: options?.signal,
  })
  if (!res.ok) await parseDetailOrThrow(res, 'navigateCodeGraph')
  return res.json()
}

export async function getCodeGraphFreshness(
  workspace: string,
): Promise<CodeGraphFreshnessResponse> {
  const params = new URLSearchParams({ workspace })
  const res = await fetch(`${apiBaseUrl()}/code-graph/freshness?${params}`, {
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) await parseDetailOrThrow(res, 'getCodeGraphFreshness')
  return res.json()
}

export async function getCodeGraphCapabilities(
  workspace: string,
): Promise<CodeGraphLanguageCapability[]> {
  const params = new URLSearchParams({ workspace })
  const res = await fetch(`${apiBaseUrl()}/code-graph/capabilities?${params}`, {
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) await parseDetailOrThrow(res, 'getCodeGraphCapabilities')
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
