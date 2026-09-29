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
      /** Already downloaded and verified: only the restart is left. */
      ready?: boolean
    }
  | { status: 'error'; title: string; message: string }

/**
 * How far along an update is.
 *
 * `total` is absent when the release server sends no Content-Length, which
 * is the one case a percentage cannot be shown — the bar says how much has
 * arrived instead of pretending to know how much is left.
 *
 * `ready` means the verified update is on disk and waits for the user: it
 * installs on "Restart now", or the next time EvoFlux quits.
 */
export type AppUpdateProgress =
  | { phase: 'downloading'; downloaded: number; total?: number | null }
  | { phase: 'verifying' }
  | { phase: 'ready' }
  | { phase: 'installing' }

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

function assertDesktopUpdater() {
  const platform = getPlatform()
  if (!platform.isTauri || platform.os === 'ios' || platform.os === 'android') {
    throw new Error('App updates are only available in the EvoFlux desktop app.')
  }
  if (platform.os === 'linux') {
    throw new Error('Linux updates are installed with a newer EvoFlux .deb package.')
  }
}

/**
 * Download and verify the update, and keep it for the restart. Nothing is
 * installed and EvoFlux keeps running.
 */
export async function downloadAppUpdate(): Promise<void> {
  assertDesktopUpdater()
  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('app_download_update')
}

/** Close EvoFlux, install the downloaded update, and start it again. */
export async function restartToUpdate(): Promise<void> {
  assertDesktopUpdater()
  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('app_restart_to_update')
}
