/**
 * useKeyboardShortcuts — registers window-level Ctrl+<key> shortcuts.
 *
 * Cross-platform note: we use ``Ctrl`` everywhere (Mac included). The
 * Mac convention is ``⌘`` but the desktop shell positions itself as a
 * tool with a power-user feel where Ctrl is the consistent modifier
 * regardless of OS. ``e.metaKey`` (⌘ on Mac, Win-key on Windows) is
 * explicitly excluded so the OS-level shortcuts (⌘W, ⌘Q, etc.) keep
 * working.
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

type ShortcutMap = Partial<Record<string, () => void>>

// On Windows/Linux, Ctrl is also the OS text-editing modifier (paste, copy,
// cut, select-all, undo, redo). If one of these keys is pressed while an
// editable element has focus, let it through untouched instead of firing an
// app shortcut — otherwise e.g. Ctrl+V while typing fires the app's 'v'
// shortcut instead of pasting (Mac is unaffected since paste there is
// Cmd+V, and metaKey is already excluded below).
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
      if (!e.ctrlKey || e.metaKey) return
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
