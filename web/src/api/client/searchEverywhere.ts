import type { SearchEverywhereResponse } from '../types'
import { apiUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'

export async function searchEverywhere(
  workspace: string,
  query: string,
  limit = 50,
  signal?: AbortSignal,
): Promise<SearchEverywhereResponse> {
  const params = new URLSearchParams({ workspace })
  const res = await fetch(apiUrl(`/team/workspace/search-everywhere?${params}`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ query, limit }),
    signal,
  })
  if (!res.ok) await parseDetailOrThrow(res, 'searchEverywhere')
  return res.json()
}
