/**
 * useKeyboardShortcuts — registers window-level primary-modifier shortcuts.
 *
 * macOS uses Command; Windows and Linux use Ctrl. The inactive modifier is
 * excluded so OS-level shortcuts keep their native behavior.
 *
 * Shortcuts map: key (lowercase) → handler function.
 *
 * Usage:
 *   useKeyboardShortcuts({
 *     a: () => setShowAgentInfo(v => !v),
 *     b: () => sidebar.toggle(),
 *   })
 */

import { useEffect, useLayoutEffect, useRef } from 'react'
import { isPrimaryShortcut } from '@/lib/keyboard-shortcuts'

type ShortcutMap = Partial<Record<string, () => void>>

// The primary modifier is also the OS text-editing modifier (paste, copy,
// cut, select-all, undo, redo). If one of these keys is pressed while an
// editable element has focus, let it through untouched instead of firing an
// app shortcut — otherwise paste can fire the app's 'v' shortcut.
const EDITABLE_RESERVED_KEYS = new Set(['v', 'c', 'x', 'a', 'z', 'y'])

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable
}

export function useKeyboardShortcuts(shortcuts: ShortcutMap): void {
  // Keep ref in sync with the latest shortcuts map without re-registering
  // the event listener. useLayoutEffect runs synchronously after DOM mutations
  // so the ref is always current before any user interaction.
  const ref = useRef(shortcuts)
  useLayoutEffect(() => {
    ref.current = shortcuts
  })

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!isPrimaryShortcut(e)) return
      const key = e.key.toLowerCase()
      if (EDITABLE_RESERVED_KEYS.has(key) && isEditableTarget(e.target)) return
      const fn = ref.current[key]
      if (fn) {
        e.preventDefault()
        fn()
      }
    }

    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, []) // runs once — ref always has latest shortcuts
}
