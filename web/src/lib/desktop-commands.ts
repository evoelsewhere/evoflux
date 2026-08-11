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

function insertTextAtCursor(text: string): void {
  const active = document.activeElement

  if (active instanceof HTMLTextAreaElement || active instanceof HTMLInputElement) {
    const proto = active instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
    const start = active.selectionStart ?? active.value.length
    const end = active.selectionEnd ?? active.value.length
    setter?.call(active, active.value.slice(0, start) + text + active.value.slice(end))
    // Native setter bypasses React's value tracker, so React only notices the
    // change once a real 'input' event fires (same trick RTL/Enzyme use).
    active.dispatchEvent(new Event('input', { bubbles: true }))
    const caret = start + text.length
    active.setSelectionRange(caret, caret)
    return
  }

  if (active instanceof HTMLElement && active.isContentEditable) {
    document.execCommand('insertText', false, text)
  }
}

async function pasteFromClipboard(): Promise<void> {
  // Chromium (WebView2) and WebKit (WKWebView) both no-op
  // document.execCommand('paste') for security, so reading the clipboard has
  // to go through Tauri's native clipboard-manager plugin instead.
  try {
    const { readText } = await import('@tauri-apps/plugin-clipboard-manager')
    const text = await readText()
    if (text) insertTextAtCursor(text)
  } catch {
    // Clipboard empty, non-text content, or read denied — nothing to paste.
  }
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
    case 'edit_cut':
      execCommand('cut')
      break
    case 'edit_copy':
      execCommand('copy')
      break
    case 'edit_paste':
      void pasteFromClipboard()
      break
    case 'edit_select_all':
      execCommand('selectAll')
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
