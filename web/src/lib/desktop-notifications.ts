import { getPlatform } from '@/hooks/use-platform'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import type { NotificationActivation } from '@/lib/notification-activation'
import { addInboxNotification } from '@/lib/notification-inbox'
import { translateText } from '@/i18n'

export type DesktopNotificationKind =
  | 'assistant_done'
  | 'background_done'
  | 'reminder_fired'
  | 'question_asked'
  | 'permission_asked'
  | 'agent_not_configured'
  | 'terminal_error'
  | 'goal_blocked'
export type DesktopNotificationStatus = 'sent' | 'disabled' | 'unsupported' | 'permission-denied' | 'error'

export interface DesktopNotificationPayload {
  kind: DesktopNotificationKind
  title: string
  body: string
  activation?: NotificationActivation
}

export interface DesktopNotificationResult {
  status: DesktopNotificationStatus
  message: string
}

const ENABLED_KEY = STORAGE_KEYS.desktopNotifications.enabled
const SOUND_ENABLED_KEY = STORAGE_KEYS.desktopNotifications.soundEnabled

let permissionRequested = false

function formatNotificationError(err: unknown): string {
  if (err instanceof Error) return err.message
  if (typeof err === 'string') return err
  try {
    const serialized = JSON.stringify(err)
    return serialized && serialized !== '{}' ? serialized : 'Native notification failed.'
  } catch {
    return String(err || 'Native notification failed.')
  }
}

function isTauriRuntime(): boolean {
  return getPlatform().isTauri
}

function isMobileTauriRuntime(): boolean {
  const platform = getPlatform()
  return platform.isTauri && (platform.os === 'ios' || platform.os === 'android')
}

export function areDesktopNotificationsEnabled(): boolean {
  if (typeof window === 'undefined') return true
  return window.localStorage.getItem(ENABLED_KEY) !== 'false'
}

export function setDesktopNotificationsEnabled(enabled: boolean): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(ENABLED_KEY, String(enabled))
}

export function areDesktopNotificationSoundsEnabled(): boolean {
  if (typeof window === 'undefined') return true
  return window.localStorage.getItem(SOUND_ENABLED_KEY) !== 'false'
}

export function setDesktopNotificationSoundsEnabled(enabled: boolean): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(SOUND_ENABLED_KEY, String(enabled))
}

async function playNotificationSound(): Promise<void> {
  if (!areDesktopNotificationSoundsEnabled()) return
  let objectUrl: string | undefined
  try {
    const { getSelectedNotificationSound } = await import('@/lib/notification-sound-library')
    const sound = await getSelectedNotificationSound()
    const source = sound ? (objectUrl = URL.createObjectURL(sound)) : '/notification.wav'
    const audio = new Audio(source)
    audio.onended = () => { if (objectUrl) URL.revokeObjectURL(objectUrl) }
    audio.onerror = () => { if (objectUrl) URL.revokeObjectURL(objectUrl) }
    await audio.play()
  } catch (err) {
    if (objectUrl) URL.revokeObjectURL(objectUrl)
    console.warn('desktop notification sound failed', err)
  }
}

export function isBackgroundCompletion(toolName: string, result: string | undefined): boolean {
  if (toolName !== 'bg' || !result) return false
  return /PID \d+: (?:exited|stopped)/.test(result)
}

async function shouldNotify(options: { force?: boolean } = {}): Promise<DesktopNotificationResult | null> {
  if (!isTauriRuntime()) {
    return { status: 'unsupported', message: 'Native app notifications only work in the Tauri app.' }
  }
  if (!areDesktopNotificationsEnabled()) {
    return { status: 'disabled', message: 'App notifications are disabled.' }
  }
  if (options.force) return null
  if (isMobileTauriRuntime()) return null

  try {
    const { getCurrentWindow } = await import('@tauri-apps/api/window')
    const appWindow = getCurrentWindow()
    const [focused, visible, minimized] = await Promise.all([
      appWindow.isFocused(),
      appWindow.isVisible(),
      appWindow.isMinimized(),
    ])
    return !focused || !visible || minimized
      ? null
      : { status: 'disabled', message: 'Desktop notifications are skipped while the app window is focused.' }
  } catch (err) {
    console.warn('desktop notification focus check failed', err)
    return { status: 'error', message: 'Could not check app window focus state.' }
  }
}

export async function sendDesktopNotification(
  payload: DesktopNotificationPayload,
  options: { force?: boolean; trackInbox?: boolean } = {},
): Promise<DesktopNotificationResult> {
  const skipped = await shouldNotify(options)
  if (skipped) return skipped

  try {
    const { isPermissionGranted, requestPermission } = await import('@tauri-apps/plugin-notification')
    let granted = await isPermissionGranted()
    if (!granted && !permissionRequested) {
      permissionRequested = true
      granted = (await requestPermission()) === 'granted'
    }
    if (!granted) {
      return { status: 'permission-denied', message: 'OS notification permission was not granted.' }
    }
    const { invoke } = await import('@tauri-apps/api/core')
    if (payload.activation || getPlatform().os === 'windows') {
      try {
        await invoke('app_send_attention_notification', {
          title: translateText(payload.title),
          body: translateText(payload.body),
          activation: payload.activation
            ? {
                ...payload.activation,
                actions: payload.activation.actions?.map((action) => ({
                  ...action,
                  label: translateText(action.label),
                })),
              }
            : null,
        })
        void playNotificationSound()
        if (options.trackInbox !== false) addInboxNotification(payload)
        return { status: 'sent', message: 'Native notification sent.' }
      } catch (error) {
        if (getPlatform().os === 'windows') throw error
      }
    }
    await invoke('plugin:notification|notify', {
      options: {
        title: translateText(payload.title),
        body: translateText(payload.body),
        group: `EvoFlux-${payload.kind}`,
      },
    })
    void playNotificationSound()
    if (options.trackInbox !== false) addInboxNotification(payload)
    return { status: 'sent', message: 'Native notification sent.' }
  } catch (err) {
    console.warn('desktop notification failed', err)
    return {
      status: 'error',
      message: formatNotificationError(err),
    }
  }
}
