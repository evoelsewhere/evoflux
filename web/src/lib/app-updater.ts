import { getPlatform } from '@/hooks/use-platform'

export type AppUpdateCheckResult =
  | { status: 'unavailable'; title: string; message: string }
  | { status: 'busy'; title: string; message: string }
  | { status: 'up_to_date'; version: string }
  | {
      status: 'available'
      version: string
      current_version: string
      notes?: string | null
    }
  | { status: 'error'; title: string; message: string }

/**
 * Ask the native desktop shell to check GitHub Releases and run the signed
 * updater check. Results stay in the EvoFlux UI; Rust still owns signature
 * verification and updater bytes.
 */
export async function checkForAppUpdates(): Promise<AppUpdateCheckResult> {
  const platform = getPlatform()
  if (!platform.isTauri || platform.os === 'ios' || platform.os === 'android') {
    throw new Error('App updates are only available in the EvoFlux desktop app.')
  }
  if (platform.os === 'linux') {
    throw new Error('Linux updates are installed with a newer EvoFlux .deb package.')
  }

  const { invoke } = await import('@tauri-apps/api/core')
  return await invoke<AppUpdateCheckResult>('app_check_for_updates')
}

/** Download, verify, install, and restart through the native updater. */
export async function installAppUpdate(): Promise<void> {
  const platform = getPlatform()
  if (!platform.isTauri || platform.os === 'ios' || platform.os === 'android') {
    throw new Error('App updates are only available in the EvoFlux desktop app.')
  }
  if (platform.os === 'linux') {
    throw new Error('Linux updates are installed with a newer EvoFlux .deb package.')
  }

  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('app_install_update')
}
