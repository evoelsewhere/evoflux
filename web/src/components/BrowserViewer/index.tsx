import { useCallback, useEffect, useRef, useState } from 'react'

import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  XIcon,
  MonitorIcon,
  ArrowLeftIcon,
  ArrowRightIcon,
  RotateCwIcon,
  GlobeIcon,
  Loader2Icon,
  MousePointerClickIcon,
  MousePointerIcon,
  ExternalLinkIcon,
} from 'lucide-react'
import { ScreencastCanvas } from './ScreencastCanvas'
import type { ScreencastHandle, ScreencastStatus } from './ScreencastCanvas'

const MIN_WIDTH = 320
const MAX_WIDTH = 1200
const DEFAULT_WIDTH = 480

interface BrowserViewerProps {
  sessionId: string | null
  open: boolean
  onClose: () => void
  className?: string
}

export function BrowserViewer({
  sessionId,
  open,
  onClose,
  className,
}: BrowserViewerProps) {
  const screencastRef = useRef<ScreencastHandle>(null)
  const [status, setStatus] = useState<ScreencastStatus | null>(null)
  const [connected, setConnected] = useState(false)
  const [frameReceived, setFrameReceived] = useState(false)
  const [urlInput, setUrlInput] = useState('')
  const [urlFocused, setUrlFocused] = useState(false)
  const [interactive, setInteractive] = useState(false)
  const [width, setWidth] = useState(DEFAULT_WIDTH)
  const resizingRef = useRef(false)

  const currentUrl = status?.url ?? ''

  const handleStatus = useCallback((s: ScreencastStatus) => {
    setStatus(s)
    if (s.url && s.url !== 'about:blank') {
      setUrlInput(s.url)
    }
  }, [])

  const handleFrame = useCallback(() => {
    setFrameReceived(true)
  }, [])

  const send = useCallback((msg: Record<string, unknown>) => {
    screencastRef.current?.send(msg)
  }, [])

  const handleNavigate = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      let url = urlInput.trim()
      if (!url) return
      if (!/^https?:\/\//i.test(url) && url.includes('.')) {
        url = `https://${url}`
      }
      send({ action: 'navigate', url })
      setUrlFocused(false)
    },
    [urlInput, send],
  )

  const handleResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      resizingRef.current = true
      const startX = e.clientX
      const startWidth = width

      const onMove = (ev: MouseEvent) => {
        if (!resizingRef.current) return
        const delta = startX - ev.clientX
        const next = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth + delta))
        setWidth(next)
      }

      const onUp = () => {
        resizingRef.current = false
        window.removeEventListener('mousemove', onMove)
        window.removeEventListener('mouseup', onUp)
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
      }

      window.addEventListener('mousemove', onMove)
      window.addEventListener('mouseup', onUp)
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
    },
    [width],
  )

  const handleResizeDoubleClick = useCallback(() => {
    setWidth(DEFAULT_WIDTH)
  }, [])

  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !interactive) onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, interactive, onClose])

  const handleOpenDevTools = useCallback(async () => {
    const cdpHttp = status?.cdpHttp ?? status?.cdp_http
    if (!cdpHttp) return
    try {
      const { invoke } = await import('@tauri-apps/api/core')
      await invoke('app_open_browser_devtools', { cdpUrl: cdpHttp })
    } catch {
      window.open(cdpHttp, '_blank')
    }
  }, [status])

  if (!open || !sessionId) return null

  const isWaiting = connected && !frameReceived
  const isActive = status?.active !== false

  return (
    <>
      {/* Backdrop — click to close on mobile */}
      <div
        className="fixed inset-0 z-(--z-overlay) bg-(--color-overlay) backdrop-blur-sm sm:hidden"
        onClick={onClose}
      />

      <div
        className={cn(
          'flex flex-col overflow-hidden',
          'border-l-2 border-(--color-border-strong)',
          'bg-(--bg-page)',
          // Mobile: full-screen fixed overlay
          'fixed z-(--z-modal) inset-x-0 bottom-0 top-[env(safe-area-inset-top,0px)]',
          // Desktop: in-flow sibling of the chat column — the chat resizes
          // instead of being covered. Width driven by the drag handle via
          // a CSS var so the mobile overlay stays full-width.
          'sm:relative sm:inset-auto sm:h-full sm:min-h-0 sm:shrink-0 sm:w-[var(--browser-viewer-width)]',
          className,
        )}
        style={{ '--browser-viewer-width': `${width}px` } as React.CSSProperties}
      >
        {/* ── Resize handle ───────────────────────────────────── */}
        <div
          className="absolute left-0 top-0 bottom-0 z-(--z-panel) hidden w-2 cursor-col-resize sm:block group/handle"
          onMouseDown={handleResizeStart}
          onDoubleClick={handleResizeDoubleClick}
          title="Drag to resize · Double-click to reset"
        >
          <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-(--color-border-strong) transition-colors group-hover/handle:bg-(--accent-blue)" />
        </div>

        {/* ── Header ──────────────────────────────────────────── */}
        <div className="flex items-center gap-1.5 border-b-2 border-(--color-border-strong) bg-(--color-surface-2) px-3 py-2">
          <MonitorIcon size={14} className="shrink-0 text-(--accent-blue)" />
          <span className="flex-1 truncate text-xs font-semibold text-(--color-text)">
            {status?.title || 'Browser'}
          </span>

          <div
            className={cn(
              'h-2 w-2 shrink-0 rounded-full',
              connected
                ? isActive
                  ? 'bg-(--accent-green)'
                  : 'bg-(--accent-orange)'
                : 'bg-(--color-text-subtle)',
            )}
            title={
              connected
                ? isActive ? 'Live' : 'Waiting for browser'
                : 'Disconnected'
            }
          />

          <button
            onClick={() => setInteractive(!interactive)}
            className={cn(
              'inline-flex h-6 items-center gap-1 rounded-md px-2 text-xs font-semibold transition-colors border',
              interactive
                ? 'border-(--accent-blue) bg-(--accent-blue) text-(--color-text-on-accent)'
                : 'border-(--color-border-strong) bg-(--bg-page) text-(--color-text-2) hover:bg-(--color-surface-2) hover:text-(--color-text)',
            )}
            title={interactive ? 'Interaction ON — click/type in browser' : 'Enable interaction'}
          >
            {interactive ? <MousePointerClickIcon size={11} /> : <MousePointerIcon size={11} />}
            <span>{interactive ? 'ON' : 'Interact'}</span>
          </button>

          {(status?.cdpHttp || status?.cdp_http) && (
            <button
              onClick={handleOpenDevTools}
              className="inline-flex h-6 w-6 items-center justify-center rounded-md border border-(--color-border-strong) bg-(--bg-page) text-(--color-text-2) transition-colors hover:bg-(--color-surface-2) hover:text-(--color-text)"
              title="Open DevTools in native window"
            >
              <ExternalLinkIcon size={11} />
            </button>
          )}

          <Button
            variant="ghost"
            size="icon-xs"
            className="text-(--color-text-2) hover:text-(--color-text)"
            onClick={onClose}
          >
            <XIcon size={12} />
          </Button>
        </div>

        {/* ── Canvas viewport ─────────────────────────────────── */}
        <div className="relative min-h-0 flex-1 bg-(--bg-key)">
          <ScreencastCanvas
            ref={screencastRef}
            sessionId={sessionId}
            interactive={interactive}
            onStatus={handleStatus}
            onConnected={setConnected}
            onFrame={handleFrame}
            className="absolute inset-0"
          />

          {(!connected || isWaiting || !isActive) && (
            <div className="absolute inset-0 flex items-center justify-center bg-(--bg-page)">
              <div className="text-center">
                {!connected ? (
                  <>
                    <Loader2Icon size={28} className="mx-auto mb-3 animate-spin text-(--accent-blue)" />
                    <p className="text-sm font-medium text-(--color-text-2)">Connecting to browser…</p>
                    <p className="mt-1 text-xs text-(--color-text-muted)">Waiting for WebSocket</p>
                  </>
                ) : !isActive ? (
                  <>
                    <GlobeIcon size={28} className="mx-auto mb-3 text-(--color-text-muted)" />
                    <p className="text-sm font-medium text-(--color-text-2)">Browser not active</p>
                    <p className="mt-1 text-xs text-(--color-text-muted)">The agent will open a browser when needed</p>
                  </>
                ) : (
                  <>
                    <Loader2Icon size={28} className="mx-auto mb-3 animate-spin text-(--accent-blue)" />
                    <p className="text-sm font-medium text-(--color-text-2)">Waiting for first frame…</p>
                  </>
                )}
              </div>
            </div>
          )}

          {interactive && connected && isActive && (
            <div className="absolute top-2 left-1/2 -translate-x-1/2 rounded-full border border-(--accent-blue) bg-(--accent-blue-soft) px-3 py-1 text-xs font-semibold text-(--accent-blue-text) pointer-events-none">
              Click & type in browser · Esc to exit
            </div>
          )}
        </div>

        {/* ── URL bar ─────────────────────────────────────────── */}
        <form
          onSubmit={handleNavigate}
          className="flex items-center gap-1 border-t-2 border-(--color-border-strong) bg-(--color-surface-2) px-2 py-1.5"
        >
          <button type="button" onClick={() => send({ action: 'back' })} className={navBtnClass} title="Back">
            <ArrowLeftIcon size={13} />
          </button>
          <button type="button" onClick={() => send({ action: 'forward' })} className={navBtnClass} title="Forward">
            <ArrowRightIcon size={13} />
          </button>
          <button type="button" onClick={() => send({ action: 'reload' })} className={navBtnClass} title="Reload">
            <RotateCwIcon size={12} />
          </button>
          <input
            type="text"
            value={urlFocused ? urlInput : currentUrl || urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            onFocus={() => { setUrlInput(currentUrl || urlInput); setUrlFocused(true) }}
            onBlur={() => setUrlFocused(false)}
            placeholder="Enter URL…"
            className={cn(
              'flex-1 truncate rounded-md border border-(--color-border-strong) px-2.5 py-1 text-xs',
              'bg-(--bg-page) text-(--color-text) font-mono',
              'outline-none transition-colors',
              'hover:border-(--accent-blue)/40',
              'focus:border-(--accent-blue) focus:ring-1 focus:ring-(--accent-blue)/30',
            )}
            spellCheck={false}
          />
        </form>

        {/* ── Tab strip ───────────────────────────────────────── */}
        {status?.tabs && status.tabs.length > 0 && (
          <div className="flex items-center gap-1 border-t border-(--color-border-strong) bg-(--color-surface-2) px-2 py-1.5 overflow-x-auto">
            {status.tabs.map((tab) => {
              const isActiveTab = tab.url === currentUrl
              return (
                <button
                  key={tab.index}
                  onClick={() => send({ action: 'switch_tab', index: tab.index })}
                  className={cn(
                    'shrink-0 truncate rounded-md px-2.5 py-1 text-xs max-w-[140px] transition-colors border',
                    isActiveTab
                      ? 'border-(--accent-blue) bg-(--accent-blue-soft) text-(--accent-blue-text) font-semibold'
                      : 'border-transparent bg-(--bg-page) text-(--color-text-2) hover:bg-(--color-surface-2) hover:text-(--color-text)',
                  )}
                  title={`${tab.title}\n${tab.url}`}
                >
                  {tab.title || tab.url || `Tab ${tab.index + 1}`}
                </button>
              )
            })}
          </div>
        )}
      </div>
    </>
  )
}

const navBtnClass = cn(
  'inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md',
  'border border-(--color-border-strong) bg-(--bg-page)',
  'text-(--color-text-2) transition-colors',
  'hover:bg-(--color-surface-2) hover:text-(--color-text)',
)
