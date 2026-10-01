import { STORAGE_KEYS } from '@/lib/storage-keys'
import type { DesktopNotificationKind } from '@/lib/desktop-notifications'
import type { NotificationActivation } from '@/lib/notification-activation'

export interface InboxNotification {
  id: string
  kind: DesktopNotificationKind
  title: string
  body: string
  createdAt: number
  readAt: number | null
  activation?: NotificationActivation
}

const STORAGE_KEY = STORAGE_KEYS.desktopNotifications.inbox
const CHANGE_EVENT = 'evoflux:notification-inbox-changed'
const MAX_NOTIFICATIONS = 50

export interface InboxChange {
  unreadCount: number
  newNotification: boolean
}

function readAll(): InboxNotification[] {
  if (typeof window === 'undefined') return []
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '[]')
    if (!Array.isArray(value)) return []
    return value.filter((item): item is InboxNotification =>
      !!item && typeof item === 'object'
      && typeof item.id === 'string'
      && typeof item.kind === 'string'
      && typeof item.title === 'string'
      && typeof item.body === 'string'
      && typeof item.createdAt === 'number'
      && (typeof item.readAt === 'number' || item.readAt === null),
    ).slice(0, MAX_NOTIFICATIONS)
  } catch {
    return []
  }
}

function writeAll(items: InboxNotification[], newNotification = false): void {
  if (typeof window === 'undefined') return
  try {
    const savedItems = items.slice(0, MAX_NOTIFICATIONS)
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(savedItems))
    window.dispatchEvent(new CustomEvent<InboxChange>(CHANGE_EVENT, {
      detail: {
        unreadCount: savedItems.filter((item) => item.readAt === null).length,
        newNotification,
      },
    }))
  } catch (error) {
    console.warn('notification inbox could not be saved', error)
  }
}

function duplicateOf(items: InboxNotification[], notification: Omit<InboxNotification, 'id' | 'createdAt' | 'readAt'>, now: number): boolean {
  const requestId = notification.activation?.requestId
  if (requestId) {
    return items.some((item) => item.activation?.requestId === requestId && item.kind === notification.kind)
  }
  return items.some((item) =>
    item.kind === notification.kind
    && item.title === notification.title
    && item.body === notification.body
    && now - item.createdAt < 15_000,
  )
}

export function listInboxNotifications(): InboxNotification[] {
  return readAll()
}

export function addInboxNotification(
  notification: Omit<InboxNotification, 'id' | 'createdAt' | 'readAt'>,
): void {
  const items = readAll()
  const now = Date.now()
  if (duplicateOf(items, notification, now)) return
  const id = globalThis.crypto?.randomUUID?.() ?? `${now}-${Math.random().toString(36).slice(2)}`
  writeAll([{ ...notification, id, createdAt: now, readAt: null }, ...items], true)
}

export function markInboxNotificationRead(id: string): void {
  const items = readAll()
  const now = Date.now()
  let changed = false
  const next = items.map((item) => {
    if (item.id !== id || item.readAt !== null) return item
    changed = true
    return { ...item, readAt: now }
  })
  if (changed) writeAll(next)
}

export function markInboxNotificationReadByActivation(activation: NotificationActivation): void {
  const items = readAll()
  const now = Date.now()
  let changed = false
  const next = items.map((item) => {
    const target = item.activation
    if (
      !target || item.readAt !== null
      || target.sessionId !== activation.sessionId
      || target.eventKind !== activation.eventKind
      || target.requestId !== activation.requestId
    ) return item
    changed = true
    return { ...item, readAt: now }
  })
  if (changed) writeAll(next)
}

export function markAllInboxNotificationsRead(): void {
  const now = Date.now()
  const items = readAll()
  if (!items.some((item) => item.readAt === null)) return
  writeAll(items.map((item) => item.readAt === null ? { ...item, readAt: now } : item))
}

export function subscribeToInboxNotifications(onChange: (change?: InboxChange) => void): () => void {
  if (typeof window === 'undefined') return () => {}
  const onInboxChange = (event: Event) => {
    onChange((event as CustomEvent<InboxChange>).detail)
  }
  const onStorageChange = () => onChange()
  window.addEventListener(CHANGE_EVENT, onInboxChange)
  window.addEventListener('storage', onStorageChange)
  return () => {
    window.removeEventListener(CHANGE_EVENT, onInboxChange)
    window.removeEventListener('storage', onStorageChange)
  }
}
