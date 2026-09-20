import type { AppSearchResponse } from '../types'
import { apiUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'

/**
 * Search everything the application owns — sessions, the dialogue inside
 * them, Coding projects and workspaces, Memory pages, scheduled tasks, agents
 * and skills. Repository contents come from `searchEverywhere` instead, which
 * needs an authorized workspace; this one answers in every mode.
 */
export async function searchApp(
  query: string,
  limit = 40,
  signal?: AbortSignal,
): Promise<AppSearchResponse> {
  const res = await fetch(apiUrl('/team/search-app'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ query, limit }),
    signal,
  })
  if (!res.ok) await parseDetailOrThrow(res, 'searchApp')
  return res.json()
}
