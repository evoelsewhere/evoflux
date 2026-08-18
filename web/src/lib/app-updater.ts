import { getPlatform } from '@/hooks/use-platform'

/**
 * Ask the native desktop shell to check GitHub Releases and run the signed
 * updater flow. The Rust command owns dialogs, signature verification,
 * installation, and restart so web content never handles updater bytes.
 */
export async function checkForAppUpdates(): Promise<void> {
  const platform = getPlatform()
  if (!platform.isTauri || platform.os === 'ios' || platform.os === 'android') {
    throw new Error('App updates are only available in the EvoFlux desktop app.')
  }

  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('app_check_for_updates')
}
