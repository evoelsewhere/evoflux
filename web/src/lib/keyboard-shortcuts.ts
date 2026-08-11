import { getPlatform, type OS } from '@/hooks/use-platform'

export function usesCommandModifier(os: OS = getPlatform().os): boolean {
  return os === 'macos'
}

export function formatShortcutLabel(shortcut: string, os: OS = getPlatform().os): string {
  if (shortcut.startsWith('^')) {
    const key = shortcut.slice(1)
    return usesCommandModifier(os) ? `⌘+${key}` : `Ctrl+${key}`
  }
  if (shortcut.startsWith('Ctrl+')) {
    const key = shortcut.slice(5)
    return usesCommandModifier(os) ? `⌘+${key}` : `Ctrl+${key}`
  }
  return shortcut
}

export function isPrimaryShortcut(event: KeyboardEvent, os: OS = getPlatform().os): boolean {
  return usesCommandModifier(os)
    ? event.metaKey && !event.ctrlKey
    : event.ctrlKey && !event.metaKey
}

export function dispatchPrimaryShortcut(key: string): void {
  const command = usesCommandModifier()
  window.dispatchEvent(
    new KeyboardEvent('keydown', {
      key,
      ctrlKey: !command,
      metaKey: command,
      bubbles: true,
    }),
  )
}
