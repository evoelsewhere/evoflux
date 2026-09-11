import { apiUrl } from '../base-url'
import type { LanguageServerInstallJob, LanguageServerOverview } from '../types'
import { parseDetailOrThrow } from './_shared'

export async function getLanguageServers(
  workspaces: readonly string[],
): Promise<LanguageServerOverview> {
  const res = await fetch(apiUrl('/team/workspace/language-servers/status'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ workspaces }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'getLanguageServers')
  return res.json()
}

/** Start an install. Resolves when it has *started*, not when it finishes;
 *  progress arrives on the next status poll. */
export async function installLanguageServer(
  languageId: string,
): Promise<LanguageServerInstallJob> {
  const res = await fetch(
    apiUrl(`/team/workspace/language-servers/${encodeURIComponent(languageId)}/install`),
    { method: 'POST', headers: { Accept: 'application/json' } },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'installLanguageServer')
  return res.json()
}

export async function dismissLanguageServerInstallError(
  languageId: string,
): Promise<void> {
  const res = await fetch(
    apiUrl(
      `/team/workspace/language-servers/${encodeURIComponent(languageId)}/install/dismiss`,
    ),
    { method: 'POST' },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'dismissLanguageServerInstallError')
}
