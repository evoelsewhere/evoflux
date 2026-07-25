/**
 * TerminalPanel — EvoFlux's AI Terminal: real interactive PTYs (xterm.js) over
 * WebSockets to `WS /team/{sessionId}/terminal`. The shell runs in the
 * session's mode-aware cwd, so vim/htop/colors/arrow-keys/Ctrl-C all work.
 *
 * Supports multiple terminals per session (tabs) — each tab is its own PTY,
 * restored from the backend on mount. "Send to agent" hands the active tab's
 * selection (or recent scrollback) to the chat composer via the
 * `evoflux:composer-insert` event.
 */
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { motion } from 'framer-motion'
import { Plus, Send, X, TerminalSquare } from 'lucide-react'
import { apiBaseUrl } from '@/api/base-url'
import { withTokenParam } from '@/api/auth'
import { panelTransition, useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'

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
  mode,
  onClose,
}: {
  sessionId: string | null
  mode: string
  onClose: () => void
}) {
  const [tabs, setTabs] = useState<string[]>([])
  const [activeId, setActiveId] = useState<string>('')
  const nextIdRef = useRef(2)
  const instancesRef = useRef<Map<string, TerminalHandle>>(new Map())

  // Restore the session's live terminals on mount so tabs survive a reload;
  // otherwise open a single default tab.
  useEffect(() => {
    // No session → nothing to restore; the render guards on sessionId and
    // shows the empty state, so we don't touch tab state here.
    if (!sessionId) return
    let alive = true
    void (async () => {
      let ids: string[] = []
      try {
        const res = await fetch(`${apiBaseUrl()}/team/${sessionId}/terminals`)
        if (res.ok) {
          const body = (await res.json()) as { terminals: { id: string }[] }
          ids = body.terminals.map((t) => t.id)
        }
      } catch {
        /* offline / no backend yet — fall through to a default tab */
      }
      if (!alive) return
      if (ids.length === 0) ids = ['1']
      setTabs(ids)
      setActiveId(ids[0])
      nextIdRef.current = Math.max(1, ...ids.map((n) => Number(n) || 0)) + 1
    })()
    return () => {
      alive = false
    }
  }, [sessionId])

  const addTab = () => {
    const id = String(nextIdRef.current++)
    setTabs((prev) => [...prev, id])
    setActiveId(id)
  }

  const closeTab = (id: string) => {
    if (sessionId) {
      void fetch(`${apiBaseUrl()}/team/${sessionId}/terminals/${encodeURIComponent(id)}`, {
        method: 'DELETE',
      }).catch(() => {})
    }
    instancesRef.current.delete(id)
    setTabs((prev) => {
      const next = prev.filter((t) => t !== id)
      setActiveId((cur) => (cur === id ? next[next.length - 1] ?? '' : cur))
      return next
    })
  }

  const sendActiveToAgent = () => instancesRef.current.get(activeId)?.sendToAgent()
  const preset = useMotionPreset()
  const slideOffset = 16 * preset.distance

  return (
    <motion.div
      className="flex h-full min-h-0 flex-col overflow-hidden rounded-l-xl bg-[#0d1117]"
      initial={{ opacity: 0, x: slideOffset }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: slideOffset * 0.5 }}
      transition={panelTransition(preset)}
    >
      <div className="flex items-center gap-1 border-b border-(--color-border) bg-(--bg-key) pl-2 pr-1">
        <TerminalSquare size={13} className="shrink-0 text-(--color-text-subtle)" />
        <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto py-1">
          {tabs.map((id, i) => (
            <div
              key={id}
              onClick={() => setActiveId(id)}
              className={cn(
                'group flex shrink-0 cursor-pointer items-center gap-1 rounded px-2 py-0.5 text-[11px]',
                id === activeId
                  ? 'bg-(--bg-subtle) text-(--color-text)'
                  : 'text-(--color-text-muted) hover:text-(--color-text)',
              )}
            >
              <span className="font-mono">sh {i + 1}</span>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  closeTab(id)
                }}
                aria-label="Close terminal tab"
                className="rounded opacity-0 hover:bg-(--bg-key) group-hover:opacity-100"
              >
                <X size={11} />
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={addTab}
            disabled={!sessionId}
            aria-label="New terminal"
            title="New terminal"
            className="shrink-0 rounded p-0.5 text-(--color-text-muted) hover:bg-(--bg-subtle) hover:text-(--color-text) disabled:opacity-40"
          >
            <Plus size={13} />
          </button>
        </div>
        <span className="shrink-0 font-mono text-[10px] text-(--color-text-subtle)">{mode}</span>
        <button
          type="button"
          onClick={sendActiveToAgent}
          disabled={!activeId}
          title="Send selection (or recent output) to the chat composer"
          className="flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-(--color-text-muted) transition-colors hover:bg-(--bg-subtle) hover:text-(--color-text) disabled:opacity-40"
        >
          <Send size={12} />
          Send to agent
        </button>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close terminal panel"
          className="shrink-0 rounded p-0.5 text-(--color-text-muted) hover:text-(--color-text)"
        >
          <X size={14} />
        </button>
      </div>
      {sessionId ? (
        <div className="relative min-h-0 flex-1">
          {tabs.map((id) => (
            <div
              key={id}
              className="absolute inset-0"
              style={{ display: id === activeId ? 'block' : 'none' }}
            >
              <TerminalInstance
                ref={(el) => {
                  if (el) instancesRef.current.set(id, el)
                  else instancesRef.current.delete(id)
                }}
                sessionId={sessionId}
                terminalId={id}
                active={id === activeId}
              />
            </div>
          ))}
          {tabs.length === 0 && (
            <div className="flex h-full items-center justify-center p-4 text-xs text-(--color-text-subtle)">
              No terminals — click + to open one.
            </div>
          )}
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center p-4 text-xs text-(--color-text-subtle)">
          Start a session to open a terminal.
        </div>
      )}
    </motion.div>
  )
}
