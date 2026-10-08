import { apiBaseUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'

export type LocalSttRuntimeJob = {
  phase: 'downloading_runtime' | 'downloading_model' | 'verifying' | 'extracting' | 'checking' | 'failed'
  runtime_version: string
  model_version: string
  bytes_done: number
  bytes_total: number
  started_at: string
  error: string | null
}

export type LocalSttRuntimeStatus = {
  available: boolean
  state: 'unavailable' | 'not_installed' | 'installing' | 'ready' | 'needs_repair' | 'failed'
  platform: string | null
  model_id: string
  runtime_version: string | null
  model_version: string | null
  download_bytes: number | null
  install_bytes: number | null
  installed_runtime_version: string | null
  installed_model_version: string | null
  healthy: boolean
  job: LocalSttRuntimeJob | null
}

async function request(method: string, action = ''): Promise<LocalSttRuntimeStatus> {
  const response = await fetch(`${apiBaseUrl()}/voice/runtime${action}`, {
    method,
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) await parseDetailOrThrow(response, `Local STT ${method.toLowerCase()}`)
  return response.json()
}

export const getLocalSttRuntime = () => request('GET', '/status')
export const installLocalSttRuntime = () => request('POST', '/install')
export const cancelLocalSttInstall = () => request('POST', '/install/cancel')
export const checkLocalSttRuntime = () => request('POST', '/check')

export async function dismissLocalSttError(): Promise<void> {
  const response = await fetch(`${apiBaseUrl()}/voice/runtime/install/dismiss`, { method: 'POST' })
  if (!response.ok) await parseDetailOrThrow(response, 'Dismiss Local STT error')
}

export async function uninstallLocalSttRuntime(): Promise<void> {
  const response = await fetch(`${apiBaseUrl()}/voice/runtime`, { method: 'DELETE' })
  if (!response.ok) await parseDetailOrThrow(response, 'Remove Local STT')
}
