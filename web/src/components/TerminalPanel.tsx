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
import { Terminal, type ITheme } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { Send } from 'lucide-react'
import { apiBaseUrl } from '@/api/base-url'
import { withTokenParam } from '@/api/auth'

const DARK_ANSI_THEME: ITheme = {
  black: '#1B1D1F',
  red: '#F87171',
  green: '#4ADE80',
  yellow: '#FBBF24',
  blue: '#60A5FA',
  magenta: '#C084FC',
  cyan: '#22D3EE',
  white: '#E5E7EA',
  brightBlack: '#8B949E',
  brightRed: '#FCA5A5',
  brightGreen: '#86EFAC',
  brightYellow: '#FDE68A',
  brightBlue: '#93C5FD',
  brightMagenta: '#D8B4FE',
  brightCyan: '#67E8F9',
  brightWhite: '#FFFFFF',
}

const LIGHT_ANSI_THEME: ITheme = {
  black: '#000000',
  red: '#CF222E',
  green: '#116329',
  yellow: '#953800',
  blue: '#0550AE',
  magenta: '#8250DF',
  cyan: '#0E7490',
  white: '#D0D7DE',
  brightBlack: '#6E7781',
  brightRed: '#A40E26',
  brightGreen: '#1A7F37',
  brightYellow: '#9A6700',
  brightBlue: '#0969DA',
  brightMagenta: '#8250DF',
  brightCyan: '#1B7C83',
  brightWhite: '#FFFFFF',
}

function terminalTheme(): ITheme {
  const root = document.documentElement
  const styles = getComputedStyle(root)
  const cssColor = (name: string, fallback: string) =>
    styles.getPropertyValue(name).trim() || fallback
  const dark = root.classList.contains('dark')

  return {
    ...(dark ? DARK_ANSI_THEME : LIGHT_ANSI_THEME),
    background: cssColor('--terminal-bg', dark ? '#171A1F' : '#F8FAFC'),
    foreground: dark ? '#D6DEE8' : '#334155',
    cursor: dark ? '#60A5FA' : '#2563EB',
    cursorAccent: cssColor('--terminal-bg', dark ? '#171A1F' : '#F8FAFC'),
    selectionBackground: dark ? '#1E4F78' : '#BFDBFE',
    selectionInactiveBackground: dark ? '#29394A' : '#DBEAFE',
    scrollbarSliderBackground: dark ? '#53596066' : '#C9CDD166',
    scrollbarSliderHoverBackground: dark ? '#6B728099' : '#9CA3AF99',
    scrollbarSliderActiveBackground: dark ? '#8B949EB3' : '#6B7280B3',
  }
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
      lineHeight: 1.25,
      theme: terminalTheme(),
      cursorBlink: true,
      scrollback: 5000,
    })
    const fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.open(containerRef.current)
    term.element?.classList.add('evoflux-terminal')
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
    const themeObserver = new MutationObserver(() => {
      term.options.theme = terminalTheme()
    })
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    })

    return () => {
      alive = false
      if (reconnectTimer) clearTimeout(reconnectTimer)
      resizeObserver.disconnect()
      themeObserver.disconnect()
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

  return <div ref={containerRef} className="h-full w-full overflow-hidden" />
})

export function TerminalPanel({
  sessionId,
  terminalId,
  active,
}: {
  sessionId: string | null
  terminalId: string
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
    <div className="group relative flex h-full min-h-0 flex-col overflow-hidden bg-(--terminal-bg)">
      {sessionId && (
        <button
          type="button"
          onClick={sendToAgent}
          title="Send selection (or recent output) to the chat composer"
          aria-label="Send terminal output to agent"
          className="absolute right-2 top-2 z-(--z-panel) flex h-7 w-7 items-center justify-center rounded-md border border-(--color-border) bg-(--bg-page)/90 text-(--color-text-muted) opacity-0 shadow-sm backdrop-blur-sm transition-[opacity,background-color,color] hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:opacity-100 group-hover:opacity-100"
        >
          <Send size={13} />
        </button>
      )}
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
