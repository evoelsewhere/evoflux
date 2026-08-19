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
  useState,
} from 'react'
import { Terminal, type ITheme } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { Send, Sparkles } from 'lucide-react'
import { apiBaseUrl, apiWsBaseUrl } from '@/api/base-url'
import { withTokenParam } from '@/api/auth'
import { codingWorkspaceFileUrl } from '@/api/client'
import type { EditorActionRequest } from '@/api/types'
import { EditorAiActionDialog } from './EditorAiActionDialog'
import { useUIStore } from '@/stores/useUIStore'
import { useToastStore } from '@/stores/useToastStore'

const DARK_ANSI_THEME: ITheme = {
  black: '#232220',
  red: '#F87171',
  green: '#55A27C',
  yellow: '#D0A04B',
  blue: '#60A5FA',
  magenta: '#C084FC',
  cyan: '#22D3EE',
  white: '#D9D5CF',
  brightBlack: '#A39D96',
  brightRed: '#FCA5A5',
  brightGreen: '#8BC6A8',
  brightYellow: '#E3BD76',
  brightBlue: '#93C5FD',
  brightMagenta: '#D8B4FE',
  brightCyan: '#67E8F9',
  brightWhite: '#F3F2EF',
}

const LIGHT_ANSI_THEME: ITheme = {
  black: '#1D1D1B',
  red: '#CF222E',
  green: '#285E47',
  yellow: '#8A641F',
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
    background: cssColor('--terminal-bg', dark ? '#1A1918' : '#F9F9F9'),
    foreground: cssColor('--color-text-2', dark ? '#D9D5CF' : '#353535'),
    cursor: cssColor('--color-accent', dark ? '#A39D96' : '#575757'),
    cursorAccent: cssColor('--terminal-bg', dark ? '#1A1918' : '#F9F9F9'),
    selectionBackground: dark ? '#A39D9640' : '#57575726',
    selectionInactiveBackground: dark ? '#A39D9620' : '#57575714',
    scrollbarSliderBackground: dark ? '#69635C66' : '#ABABAB66',
    scrollbarSliderHoverBackground: dark ? '#817A7299' : '#89867F99',
    scrollbarSliderActiveBackground: dark ? '#A39D96B3' : '#5F5D58B3',
  }
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
  collectText: () => string
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
    collectText: () => {
      const term = termRef.current
      return term ? collectText(term) : ''
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
        `${apiWsBaseUrl()}/team/${sessionId}/terminal?tid=${encodeURIComponent(terminalId)}&cols=${term.cols}&rows=${term.rows}`,
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
  workspace = null,
  activeFilePath = null,
}: {
  sessionId: string | null
  terminalId: string
  active: boolean
  workspace?: string | null
  activeFilePath?: string | null
}) {
  const instanceRef = useRef<TerminalHandle | null>(null)
  const [aiRequest, setAiRequest] = useState<EditorActionRequest | null>(null)
  const openWorkbenchTool = useUIStore((state) => state.openWorkbenchTool)
  const pushToast = useToastStore((state) => state.push)

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
  const explainFailure = async () => {
    const terminalOutput = instanceRef.current?.collectText() ?? ''
    if (!sessionId || !workspace || !activeFilePath || !terminalOutput.trim()) {
      pushToast({
        tone: 'info',
        title: 'Open a source file and select terminal output first',
      })
      return
    }
    try {
      const response = await fetch(codingWorkspaceFileUrl(workspace, activeFilePath))
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      setAiRequest({
        session_id: sessionId,
        action: 'explain_failure',
        active_file: activeFilePath,
        content: await response.text(),
        relevant_terminal_failure: terminalOutput,
      })
    } catch (error) {
      pushToast({
        tone: 'error',
        title: 'Could not prepare terminal explanation',
        description: error instanceof Error ? error.message : undefined,
      })
    }
  }

  return (
    <div className="group relative flex h-full min-h-0 flex-col overflow-hidden bg-(--terminal-bg)">
      {sessionId && (
        <div className="absolute right-2 top-2 z-(--z-panel) flex items-center gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
          <button
            type="button"
            onClick={() => { void explainFailure() }}
            title="Explain selection or recent terminal failure with AI"
            aria-label="Explain terminal failure with AI"
            className="flex h-7 w-7 items-center justify-center rounded-md border border-(--color-border) bg-(--bg-page)/90 text-(--color-accent) shadow-sm backdrop-blur-sm hover:bg-(--bg-key)"
          >
            <Sparkles size={13} />
          </button>
          <button
            type="button"
            onClick={sendToAgent}
            title="Send selection (or recent output) to the chat composer"
            aria-label="Send terminal output to agent"
            className="flex h-7 w-7 items-center justify-center rounded-md border border-(--color-border) bg-(--bg-page)/90 text-(--color-text-muted) shadow-sm backdrop-blur-sm hover:bg-(--bg-key) hover:text-(--color-text)"
          >
            <Send size={13} />
          </button>
        </div>
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
      {aiRequest && workspace && (
        <EditorAiActionDialog
          workspace={workspace}
          request={aiRequest}
          onClose={() => setAiRequest(null)}
          onOpenProblems={() => openWorkbenchTool('problems')}
        />
      )}
    </div>
  )
}
