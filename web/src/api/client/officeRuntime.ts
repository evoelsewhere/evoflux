import { apiUrl } from '../base-url'
import type { OfficeRuntimeStatus } from '../types'
import { parseDetailOrThrow } from './_shared'

export async function getOfficeRuntimeStatus(): Promise<OfficeRuntimeStatus> {
  const res = await fetch(apiUrl('/team/office-runtime/status'), {
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) await parseDetailOrThrow(res, 'getOfficeRuntimeStatus')
  return res.json()
}

/** Start the download. Resolves when it has *started*; progress arrives on
 *  the next status poll. */
export async function installOfficeRuntime(): Promise<OfficeRuntimeStatus> {
  const res = await fetch(apiUrl('/team/office-runtime/install'), {
    method: 'POST',
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) await parseDetailOrThrow(res, 'installOfficeRuntime')
  return res.json()
}

export async function dismissOfficeRuntimeError(): Promise<void> {
  const res = await fetch(apiUrl('/team/office-runtime/install/dismiss'), { method: 'POST' })
  if (!res.ok) await parseDetailOrThrow(res, 'dismissOfficeRuntimeError')
}

export async function uninstallOfficeRuntime(): Promise<void> {
  const res = await fetch(apiUrl('/team/office-runtime'), { method: 'DELETE' })
  if (!res.ok) await parseDetailOrThrow(res, 'uninstallOfficeRuntime')
}
