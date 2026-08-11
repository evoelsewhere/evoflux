import { describe, expect, it } from 'vitest'
import { formatShortcutLabel, isPrimaryShortcut } from '@/lib/keyboard-shortcuts'

describe('platform-native keyboard shortcuts', () => {
  it('formats the primary modifier for macOS', () => {
    expect(formatShortcutLabel('^K', 'macos')).toBe('⌘+K')
    expect(formatShortcutLabel('Ctrl+P', 'macos')).toBe('⌘+P')
  })

  it('formats the primary modifier for Windows and Linux', () => {
    expect(formatShortcutLabel('^K', 'windows')).toBe('Ctrl+K')
    expect(formatShortcutLabel('Ctrl+P', 'linux')).toBe('Ctrl+P')
  })

  it('accepts Command only on macOS and Ctrl only on Windows', () => {
    const commandK = { metaKey: true, ctrlKey: false } as KeyboardEvent
    const controlK = { metaKey: false, ctrlKey: true } as KeyboardEvent

    expect(isPrimaryShortcut(commandK, 'macos')).toBe(true)
    expect(isPrimaryShortcut(controlK, 'macos')).toBe(false)
    expect(isPrimaryShortcut(controlK, 'windows')).toBe(true)
    expect(isPrimaryShortcut(commandK, 'windows')).toBe(false)
  })
})
