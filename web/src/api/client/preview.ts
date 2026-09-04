/**
 * EvoFlux API client — preview group: dev servers declared in launch.json.
 *
 * Backs the browser pane's launcher. The same registry serves the agent's
 * `preview` tool, so a server started here is the one the agent reuses.
 */

import { apiBaseUrl } from '../base-url'
import { fetchWithTimeout, parseDetailOrThrow } from './_shared'
import type {
  PreviewActionResponse,
  PreviewTargetListResponse,
} from '../types'

// Starting a dev server means waiting for its port; launch.json allows up to
// 300s, so this call opts out of the client's 10s default.
const START_TIMEOUT_MS = 310_000

export async function getPreviewTargets(
  workspace: string,
  signal?: AbortSignal,
): Promise<PreviewTargetListResponse> {
  const res = await fetchWithTimeout(
    `${apiBaseUrl()}/team/preview/targets?workspace=${encodeURIComponent(workspace)}`,
    { headers: { Accept: 'application/json' }, signal },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'getPreviewTargets')
  return res.json()
}

export async function startPreviewTarget(
  workspace: string,
  name: string,
): Promise<PreviewActionResponse> {
  const res = await fetchWithTimeout(
    `${apiBaseUrl()}/team/preview/start`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ workspace, name }),
    },
    START_TIMEOUT_MS,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'startPreviewTarget')
  return res.json()
}

export async function stopPreviewTarget(
  workspace: string,
  name: string,
): Promise<PreviewActionResponse> {
  const res = await fetchWithTimeout(`${apiBaseUrl()}/team/preview/stop`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ workspace, name }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'stopPreviewTarget')
  return res.json()
}
