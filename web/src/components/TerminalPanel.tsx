/**
 * TerminalPanel — EvoFlux's AI Terminal: a real interactive PTY (xterm.js)
 * over a WebSocket to `WS /team/{sessionId}/terminal`. The shell runs in the
 * session's mode-aware cwd (coding/aim workspace, or the forge session dir),
 * so vim/htop/colors/arrow-keys/Ctrl-C all work.
 *
 * "Send to agent" hands the current selection (or the recent scrollback) to
 * the chat composer via the `evoflux:composer-insert` event — the user→agent
 * half of terminal↔agent sharing.
 */
import { useEffect, useRef } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { Send, X, TerminalSquare } from 'lucide-react'
import { apiBaseUrl } from '@/api/base-url'
import { withTokenParam } from '@/api/auth'

// Conventional dark terminal surface (terminals read as dark regardless of
// the app's light/dark theme).
const TERMINAL_THEME = {
  background: '#0d1117',
  foreground: '#d1d5db',
  cursor: '#d1d5db',
  selectionBackground: '#264f78',
  black: '#0d1117',
  red: '#f87171',
  green: '#4ade80',
  yellow: '#fbbf24',
  blue: '#60a5fa',
  magenta: '#c084fc',
  cyan: '#22d3ee',
  white: '#d1d5db',
  brightBlack: '#6b7280',
}

function terminalWsUrl(sessionId: string, cols: number, rows: number): string {
  const apiBase = apiBaseUrl()
  let wsBase: string
  if (apiBase.startsWith('http')) {
    wsBase = apiBase.replace(/^http/, 'ws')
  } else {
    const host = window.location.hostname || 'localhost'
    wsBase = `ws://${host}:8000/api`
  }
  return withTokenParam(
    `${wsBase}/team/${sessionId}/terminal?cols=${cols}&rows=${rows}`,
  )
}

function collectText(term: Terminal): string {
  const selection = term.getSelection()
  if (selection.trim()) return selection
  const buffer = term.buffer.active
  const lines: string[] = []
  const start = Math.max(0, buffer.length - 40)
  for (let i = start; i < buffer.length; i++) {
    lines.push(buffer.getLine(i)?.translateToString(true) ?? '')
  }
  return lines.join('\n').trimEnd()
}

export function TerminalPanel({
  sessionId,
  mode,
  onClose,
}: {
  sessionId: string | null
  mode: string
  onClose: () => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<Terminal | null>(null)

  useEffect(() => {
    if (!sessionId || !containerRef.current) return
    let alive = true
    let ws: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let exited = false

    const term = new Terminal({
      fontFamily: '"JetBrains Mono Variable", ui-monospace, monospace',
      fontSize: 13,
      theme: TERMINAL_THEME,
      cursorBlink: true,
      scrollback: 5000,
    })
    const fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.open(containerRef.current)
    termRef.current = term
    try {
      fitAddon.fit()
    } catch {
      /* container not laid out yet */
    }

    const sendResize = () => {
      try {
        fitAddon.fit()
      } catch {
        return
      }
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      }
    }

    const dataDisposable = term.onData((data) => {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'input', data }))
      }
    })

    function connect() {
      if (!alive) return
      const socket = new WebSocket(terminalWsUrl(sessionId!, term.cols, term.rows))
      socket.binaryType = 'arraybuffer'
      ws = socket

      socket.onopen = () => {
        if (alive) sendResize()
      }
      socket.onmessage = (ev) => {
        if (!alive) return
        if (ev.data instanceof ArrayBuffer) {
          term.write(new Uint8Array(ev.data))
        } else if (typeof ev.data === 'string') {
          try {
            const msg = JSON.parse(ev.data) as { type?: string; message?: string }
            if (msg.type === 'exit') {
              exited = true
              term.write('\r\n\x1b[90m[process exited — reopen the terminal to start a new shell]\x1b[0m\r\n')
            } else if (msg.type === 'error') {
              term.write(`\r\n\x1b[31m[terminal error: ${msg.message ?? 'unknown'}]\x1b[0m\r\n`)
            }
          } catch {
            /* ignore malformed control frames */
          }
        }
      }
      socket.onclose = () => {
        // Transport blip → reconnect (reattaches to the still-live shell and
        // replays scrollback). A clean shell exit does not reconnect.
        if (alive && !exited) {
          reconnectTimer = setTimeout(connect, 1000)
        }
      }
    }
    connect()

    const resizeObserver = new ResizeObserver(() => sendResize())
    resizeObserver.observe(containerRef.current)

    return () => {
      alive = false
      if (reconnectTimer) clearTimeout(reconnectTimer)
      resizeObserver.disconnect()
      dataDisposable.dispose()
      ws?.close()
      term.dispose()
      termRef.current = null
    }
  }, [sessionId])

  const sendToAgent = () => {
    const term = termRef.current
    if (!term) return
    const text = collectText(term)
    if (!text.trim()) return
    window.dispatchEvent(
      new CustomEvent('evoflux:composer-insert', {
        detail: { text: `Terminal output:\n\`\`\`\n${text}\n\`\`\`` },
      }),
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#0d1117]">
      <div className="flex items-center justify-between gap-2 border-b border-(--color-border) bg-(--bg-key) px-3 py-1.5">
        <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">
          <TerminalSquare size={13} />
          Terminal
          <span className="font-mono text-[10px] normal-case tracking-normal text-(--color-text-muted)">
            {mode}
          </span>
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={sendToAgent}
            title="Send selection (or recent output) to the chat composer"
            className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-(--color-text-muted) transition-colors hover:bg-(--bg-subtle) hover:text-(--color-text)"
          >
            <Send size={12} />
            Send to agent
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close terminal"
            className="rounded p-0.5 text-(--color-text-muted) hover:text-(--color-text)"
          >
            <X size={14} />
          </button>
        </div>
      </div>
      {sessionId ? (
        <div ref={containerRef} className="min-h-0 flex-1 overflow-hidden p-1" />
      ) : (
        <div className="flex flex-1 items-center justify-center p-4 text-xs text-(--color-text-subtle)">
          Start a session to open a terminal.
        </div>
      )}
    </div>
  )
}
