import { getPlatform } from '@/hooks/use-platform'
import {
  listInboxNotifications,
  markAllInboxNotificationsRead,
  subscribeToInboxNotifications,
  type InboxChange,
} from '@/lib/notification-inbox'

const BADGE_SIZE = 16
const MAX_INBOX_NOTIFICATIONS = 50

function createWindowsOverlay(unreadCount: number): number[] | null {
  if (unreadCount <= 0 || typeof document === 'undefined') return null

  const canvas = document.createElement('canvas')
  canvas.width = BADGE_SIZE
  canvas.height = BADGE_SIZE
  const context = canvas.getContext('2d', { willReadFrequently: true })
  if (!context) return null

  const accent = getComputedStyle(document.documentElement)
    .getPropertyValue('--color-accent')
    .trim()
  context.clearRect(0, 0, BADGE_SIZE, BADGE_SIZE)
  context.beginPath()
  context.arc(8, 8, 7.5, 0, Math.PI * 2)
  context.fillStyle = accent || '#D97757'
  context.fill()
  context.strokeStyle = '#FFFFFF'
  context.lineWidth = 1
  context.stroke()
  context.fillStyle = '#FFFFFF'
  context.font = unreadCount >= 10
    ? '700 7px Arial, sans-serif'
    : '700 10px Arial, sans-serif'
  context.textAlign = 'center'
  context.textBaseline = 'middle'
  context.fillText(String(Math.min(unreadCount, MAX_INBOX_NOTIFICATIONS)), 8, 8.25)
  return Array.from(context.getImageData(0, 0, BADGE_SIZE, BADGE_SIZE).data)
}

function currentUnreadCount(): number {
  return listInboxNotifications().filter((item) => item.readAt === null).length
}

/** Keep the OS taskbar / Dock indicator in sync with the local notification inbox. */
export function startNotificationDesktopBadge(): () => void {
  const { isTauri, os } = getPlatform()
  if (!isTauri || (os !== 'windows' && os !== 'macos')) return () => {}

  let stopped = false
  let stopFocusListener: (() => void) | undefined
  let pending = Promise.resolve()

  const publish = (change?: InboxChange) => {
    const unreadCount = change?.unreadCount ?? currentUnreadCount()
    const requestAttention = change?.newNotification ?? false
    pending = pending
      .catch(() => undefined)
      .then(async () => {
        if (stopped) return
        const { invoke } = await import('@tauri-apps/api/core')
        await invoke('app_update_notification_badge', {
          unreadCount,
          overlayRgba: os === 'windows' ? createWindowsOverlay(unreadCount) : null,
          requestAttention,
        })
      })
      .catch((error: unknown) => {
        console.warn('desktop notification badge could not be updated', error)
      })
  }

  const unsubscribe = subscribeToInboxNotifications(publish)
  publish()

  // Returning to the app means the user has seen the outstanding alerts.
  // Clear the unread count and Windows attention state on focus, including
  // when the app is launched directly into the foreground.
  void import('@tauri-apps/api/window')
    .then(async ({ getCurrentWindow }) => {
      const appWindow = getCurrentWindow()
      stopFocusListener = await appWindow.onFocusChanged(({ payload: focused }) => {
        if (focused) markAllInboxNotificationsRead()
      })
      if (stopped) {
        stopFocusListener()
        return
      }
      if (await appWindow.isFocused()) markAllInboxNotificationsRead()
    })
    .catch((error: unknown) => {
      console.warn('notification inbox could not clear on app focus', error)
    })

  return () => {
    stopped = true
    stopFocusListener?.()
    unsubscribe()
  }
}
