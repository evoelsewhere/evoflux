/**
 * TerminalPanel — EvoFlux's AI Terminal: real interactive PTYs (xterm.js) over
 * WebSockets to `WS /team/{sessionId}/terminal`. The shell runs in the
 * session's mode-aware cwd, so vim/htop/colors/arrow-keys/Ctrl-C all work.
 *
 * Each mounted panel owns exactly one PTY. Multiple terminals are represented
 * by independent Workbench tabs, avoiding a second nested tab strip here.
 * "Send to agent" hands this terminal's selection (or recent scrollback) to
 * the chat composer via the `evoflux:composer-insert` event.
 */
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
} from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { Send } from 'lucide-react'
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

function wsBaseUrl(): string {
  const apiBase = apiBaseUrl()
  if (apiBase.startsWith('http')) return apiBase.replace(/^http/, 'ws')
  const host = window.location.hostname || 'localhost'
  return `ws://${host}:8000/api`
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

interface TerminalHandle {
  sendToAgent: () => void
}

const TerminalInstance = forwardRef<
  TerminalHandle,
  { sessionId: string; terminalId: string; active: boolean }
>(function TerminalInstance({ sessionId, terminalId, active }, ref) {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<Terminal | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  const refit = useCallback(() => {
    const fit = fitRef.current
    const term = termRef.current
    if (!fit || !term) return
    try {
      fit.fit()
    } catch {
      return
    }
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }),
      )
    }
  }, [])

  useImperativeHandle(ref, () => ({
    sendToAgent: () => {
      const term = termRef.current
      if (!term) return
      const text = collectText(term)
      if (!text.trim()) return
      window.dispatchEvent(
        new CustomEvent('evoflux:composer-insert', {
          detail: { text: `Terminal output:\n\`\`\`\n${text}\n\`\`\`` },
        }),
      )
    },
  }), [])

  useEffect(() => {
    if (!containerRef.current) return
    let alive = true
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
    fitRef.current = fitAddon
    try {
      fitAddon.fit()
    } catch {
      /* container not laid out yet */
    }

    const dataDisposable = term.onData((data) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'input', data }))
      }
    })

    function connect() {
      if (!alive) return
      const url = withTokenParam(
        `${wsBaseUrl()}/team/${sessionId}/terminal?tid=${encodeURIComponent(terminalId)}&cols=${term.cols}&rows=${term.rows}`,
      )
      const socket = new WebSocket(url)
      socket.binaryType = 'arraybuffer'
      wsRef.current = socket

      socket.onopen = () => {
        if (alive) refit()
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
              term.write('\r\n\x1b[90m[process exited — close this tab and open a new one]\x1b[0m\r\n')
            } else if (msg.type === 'error') {
              term.write(`\r\n\x1b[31m[terminal error: ${msg.message ?? 'unknown'}]\x1b[0m\r\n`)
            }
          } catch {
            /* ignore malformed control frames */
          }
        }
      }
      socket.onclose = () => {
        if (alive && !exited) reconnectTimer = setTimeout(connect, 1000)
      }
    }
    connect()

    const resizeObserver = new ResizeObserver(() => refit())
    resizeObserver.observe(containerRef.current)

    return () => {
      alive = false
      if (reconnectTimer) clearTimeout(reconnectTimer)
      resizeObserver.disconnect()
      dataDisposable.dispose()
      wsRef.current?.close()
      term.dispose()
      termRef.current = null
      fitRef.current = null
    }
  }, [sessionId, terminalId, refit])

  // When this tab becomes visible its box regains real dimensions — refit and
  // focus so the shell fills the pane and takes keystrokes.
  useEffect(() => {
    if (active) {
      refit()
      termRef.current?.focus()
    }
  }, [active, refit])

  return <div ref={containerRef} className="h-full w-full overflow-hidden p-1" />
})

export function TerminalPanel({
  sessionId,
  terminalId,
  mode,
  active,
}: {
  sessionId: string | null
  terminalId: string
  mode: string
  active: boolean
}) {
  const instanceRef = useRef<TerminalHandle | null>(null)

  useEffect(() => {
    if (!sessionId) return
    const closeTerminal = (event: Event) => {
      const detail = (event as CustomEvent<{ tabId?: string }>).detail
      if (detail?.tabId !== terminalId) return
      void fetch(`${apiBaseUrl()}/team/${sessionId}/terminals/${encodeURIComponent(terminalId)}`, {
        method: 'DELETE',
      }).catch(() => {})
    }
    window.addEventListener('evoflux:workbench-tab-close', closeTerminal)
    return () => window.removeEventListener('evoflux:workbench-tab-close', closeTerminal)
  }, [sessionId, terminalId])

  const sendToAgent = () => instanceRef.current?.sendToAgent()

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[#0d1117]">
      <div className="flex h-9 shrink-0 items-center justify-end gap-2 border-b border-(--color-border) bg-(--bg-key) px-2">
        <span className="shrink-0 font-mono text-[10px] text-(--color-text-subtle)">{mode}</span>
        <button
          type="button"
          onClick={sendToAgent}
          disabled={!sessionId}
          title="Send selection (or recent output) to the chat composer"
          className="flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-(--color-text-muted) transition-colors hover:bg-(--bg-subtle) hover:text-(--color-text) disabled:opacity-40"
        >
          <Send size={12} />
          Send to agent
        </button>
      </div>
      {sessionId ? (
        <div className="min-h-0 flex-1">
          <TerminalInstance
            ref={instanceRef}
            sessionId={sessionId}
            terminalId={terminalId}
            active={active}
          />
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center p-4 text-xs text-(--color-text-subtle)">
          Start a session to open a terminal.
        </div>
      )}
    </div>
  )
}
