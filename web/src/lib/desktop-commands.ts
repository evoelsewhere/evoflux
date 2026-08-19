/**
 * Native desktop command bridge.
 *
 * Tauri menu/tray items live in Rust, while panel state and the command
 * palette live in React/Zustand. Rust emits a small string command and this
 * bridge fans it back into the same keyboard events the web UI already uses.
 */
import { useEffect } from 'react'
import { useUIStore } from '@/stores/useUIStore'
import { dispatchPrimaryShortcut } from '@/lib/keyboard-shortcuts'

function execCommand(command: string): void {
  // Focus the active element first so execCommand targets the right editable
  // region. Browsers require contentEditable/designMode or an editable form
  // control for clipboard commands; this mirrors the Edit menu behavior in
  // native apps and works for the chat textarea and other inputs.
  const active = document.activeElement as HTMLElement | null
  if (active && active.focus) {
    active.focus()
  }
  document.execCommand(command, false, undefined)
}

function runDesktopCommand(command: unknown): void {
  switch (command) {
    case 'command_palette':
      dispatchPrimaryShortcut('p')
      break
    case 'wiki':
      useUIStore.getState().toggleWiki()
      break
    case 'scheduler':
      useUIStore.getState().toggleScheduler()
      break
    case 'edit_undo':
      execCommand('undo')
      break
    case 'edit_redo':
      execCommand('redo')
      break
  }
}

let lastCommand: { command: unknown; timestamp: number } | null = null

export function useDesktopCommands(): void {
  useEffect(() => {
    let cleanup: (() => void) | undefined
    let cancelled = false

    ;(async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event')
        const unlisten = await listen<unknown>('desktop-command', (event) => {
          const now = Date.now()
          if (lastCommand && lastCommand.command === event.payload && now - lastCommand.timestamp < 450) return
          lastCommand = { command: event.payload, timestamp: now }
          runDesktopCommand(event.payload)
        })
        if (cancelled) {
          unlisten()
          return
        }
        cleanup = unlisten
      } catch {
        // Browser build: no Tauri event bus.
      }
    })()

    return () => {
      cancelled = true
      cleanup?.()
    }
  }, [])
}
