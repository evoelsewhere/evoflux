export interface SavedAppServer {
  base_url: string
  name?: string | null
}

export interface AppBackendStatus {
  base_url: string
  token?: string | null
  mode?: 'bundled' | 'external'
  sidecar_running: boolean
  external: boolean
  supports_bundled: boolean
  servers: SavedAppServer[]
}

export async function getAppBackendStatus(): Promise<AppBackendStatus | null> {
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    return await invoke<AppBackendStatus>('app_backend_status')
  } catch {
    return null
  }
}

export function isTauriContext(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

export async function saveAppBackendServer(baseUrl: string, name: string): Promise<AppBackendStatus> {
  if (!isTauriContext()) throw new Error('Saving servers requires the EvoFlux desktop app.')
  const { invoke } = await import('@tauri-apps/api/core')
  return await invoke<AppBackendStatus>('app_save_backend_server', { baseUrl, name })
}

export async function removeAppBackendServer(baseUrl: string): Promise<AppBackendStatus> {
  if (!isTauriContext()) throw new Error('Removing servers requires the EvoFlux desktop app.')
  const { invoke } = await import('@tauri-apps/api/core')
  return await invoke<AppBackendStatus>('app_remove_backend_server', { baseUrl })
}

export async function switchToExternalAppBackend(
  baseUrl: string,
  name: string,
  persist: boolean,
): Promise<AppBackendStatus> {
  if (!isTauriContext()) {
    // Non-Tauri (browser) context: return a minimal status so the dialog can
    // proceed and update the API base URL locally without desktop persistence.
    return {
      base_url: baseUrl,
      mode: 'external',
      sidecar_running: false,
      external: true,
      supports_bundled: false,
      servers: [],
    }
  }
  const { invoke } = await import('@tauri-apps/api/core')
  return await invoke<AppBackendStatus>('app_use_external_backend', { baseUrl, name, persist })
}

export async function switchToBundledAppBackend(): Promise<void> {
  if (!isTauriContext()) throw new Error('The builtin sidecar is only available in the EvoFlux desktop app.')
  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('app_use_bundled_backend')
}
