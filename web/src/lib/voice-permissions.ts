import { invoke } from '@tauri-apps/api/core'

import { isTauriContext } from '@/lib/app-backend'

/** Request native microphone permission when the recorder runs in Tauri. */
export async function requestVoicePermission(): Promise<void> {
  if (!isTauriContext()) return
  const granted = await invoke<boolean>('request_voice_permissions')
  if (!granted) throw new Error('Allow microphone access in your device settings, then try again.')
}
