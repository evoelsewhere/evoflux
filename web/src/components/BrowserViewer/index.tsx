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

  // ── Resize logic ──────────────────────────────────────────────────
  const handleResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      resizingRef.current = true
      const startX = e.clientX
      const startWidth = width

      const onMove = (ev: MouseEvent) => {
        if (!resizingRef.current) return
        const delta = startX - ev.clientX // dragging left = wider
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

  // Double-click resize handle to reset to default
  const handleResizeDoubleClick = useCallback(() => {
    setWidth(DEFAULT_WIDTH)
  }, [])

  // Escape to close
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !interactive) onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, interactive, onClose])

  // Open CDP DevTools in external window (M7 — Tauri only)
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
        className="fixed inset-0 z-40 bg-black/20 sm:hidden"
        onClick={onClose}
      />
      <div
        className={cn(
          'fixed z-50 flex flex-col overflow-hidden border-l border-(--color-border) bg-(--bg-card) shadow-2xl',
          // Mobile: full screen
          'inset-x-0 bottom-0 top-[env(safe-area-inset-top,0px)]',
          // Desktop: right-side panel, width controlled by state
          'sm:inset-y-0 sm:left-auto sm:right-0 sm:top-[env(safe-area-inset-top,0px)] sm:bottom-[env(safe-area-inset-bottom,0px)]',
          className,
        )}
        style={{ width: `${width}px` }}
      >
        {/* ── Resize handle (desktop only, left edge) ────────────── */}
        <div
          className="absolute left-0 top-0 bottom-0 z-10 hidden w-1.5 cursor-col-resize sm:block group/handle"
          onMouseDown={handleResizeStart}
          onDoubleClick={handleResizeDoubleClick}
          title="Drag to resize · Double-click to reset"
        >
          <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-transparent transition-colors group-hover/handle:bg-(--color-accent)/40" />
        </div>

        {/* ── Header bar ──────────────────────────────────────────── */}
        <div className="flex items-center gap-1.5 border-b border-(--color-border) px-2 py-1.5">
          <MonitorIcon size={13} className="shrink-0 text-(--color-text) opacity-40" />
          <span className="flex-1 truncate text-[11px] font-medium text-(--color-text)">
            {status?.title || 'Browser'}
          </span>

          <div
            className={cn(
              'h-1.5 w-1.5 shrink-0 rounded-full transition-colors',
              connected
                ? isActive
                  ? 'bg-green-500'
                  : 'bg-yellow-500'
                : 'bg-(--color-text) opacity-20',
            )}
            title={
              connected
                ? isActive
                  ? 'Live'
                  : 'Waiting for browser'
                : 'Disconnected'
            }
          />

          <button
            onClick={() => setInteractive(!interactive)}
            className={cn(
              'inline-flex h-5 items-center gap-1 rounded-md px-1.5 text-[9px] font-medium transition-colors',
              interactive
                ? 'bg-(--color-accent) text-white'
                : 'text-(--color-text) opacity-40 hover:bg-(--bg-key) hover:opacity-80',
            )}
            title={interactive ? 'Interaction mode ON — click/type in browser' : 'Enable interaction mode'}
          >
            {interactive ? <MousePointerClickIcon size={10} /> : <MousePointerIcon size={10} />}
            <span>{interactive ? 'ON' : 'Interact'}</span>
          </button>

          {(status?.cdpHttp || status?.cdp_http) && (
            <button
              onClick={handleOpenDevTools}
              className="inline-flex h-5 w-5 items-center justify-center rounded-md text-(--color-text) opacity-40 transition-opacity hover:bg-(--bg-key) hover:opacity-80"
              title="Open DevTools in native window"
            >
              <ExternalLinkIcon size={11} />
            </button>
          )}

          <Button
            variant="ghost"
            size="icon-xs"
            className="opacity-60 hover:opacity-100"
            onClick={onClose}
          >
            <XIcon size={12} />
          </Button>
        </div>

        {/* ── Canvas viewport ─────────────────────────────────────── */}
        <div className="relative min-h-0 flex-1 bg-black/5">
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
            <div className="absolute inset-0 flex items-center justify-center bg-(--bg-card)/80">
              <div className="text-center">
                {!connected ? (
                  <>
                    <Loader2Icon size={24} className="mx-auto mb-2 animate-spin text-(--color-text) opacity-30" />
                    <p className="text-[11px] text-(--color-text) opacity-40">Connecting to browser…</p>
                  </>
                ) : !isActive ? (
                  <>
                    <GlobeIcon size={24} className="mx-auto mb-2 text-(--color-text) opacity-20" />
                    <p className="text-[11px] text-(--color-text) opacity-40">Browser not active</p>
                    <p className="mt-1 text-[10px] text-(--color-text) opacity-25">The agent will open a browser when needed</p>
                  </>
                ) : (
                  <>
                    <Loader2Icon size={24} className="mx-auto mb-2 animate-spin text-(--color-accent) opacity-50" />
                    <p className="text-[11px] text-(--color-text) opacity-40">Waiting for first frame…</p>
                  </>
                )}
              </div>
            </div>
          )}

          {interactive && connected && isActive && (
            <div className="absolute top-1 left-1/2 -translate-x-1/2 rounded-full bg-(--color-accent)/90 px-2 py-0.5 text-[9px] font-medium text-white shadow-sm pointer-events-none">
              Click & type in browser · Esc to exit
            </div>
          )}
        </div>

        {/* ── URL bar ─────────────────────────────────────────────── */}
        <form
          onSubmit={handleNavigate}
          className="flex items-center gap-1 border-t border-(--color-border) px-2 py-1"
        >
          <button type="button" onClick={() => send({ action: 'back' })} className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-(--color-text) opacity-40 transition-opacity hover:bg-(--bg-key) hover:opacity-80" title="Back">
            <ArrowLeftIcon size={12} />
          </button>
          <button type="button" onClick={() => send({ action: 'forward' })} className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-(--color-text) opacity-40 transition-opacity hover:bg-(--bg-key) hover:opacity-80" title="Forward">
            <ArrowRightIcon size={12} />
          </button>
          <button type="button" onClick={() => send({ action: 'reload' })} className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-(--color-text) opacity-40 transition-opacity hover:bg-(--bg-key) hover:opacity-80" title="Reload">
            <RotateCwIcon size={11} />
          </button>
          <input
            type="text"
            value={urlFocused ? urlInput : currentUrl || urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            onFocus={() => { setUrlInput(currentUrl || urlInput); setUrlFocused(true) }}
            onBlur={() => setUrlFocused(false)}
            placeholder="Enter URL…"
            className={cn(
              'flex-1 truncate rounded-md border px-2 py-0.5 text-[11px]',
              'bg-(--bg-key, var(--bg-page)) text-(--color-text)',
              'outline-none transition-colors',
              'border-transparent hover:border-(--color-border)',
              'focus:border-(--focus-ring) focus:ring-1 focus:ring-(--focus-ring)/25',
            )}
            spellCheck={false}
          />
        </form>

        {/* ── Tab strip ───────────────────────────────────────────── */}
        {status?.tabs && status.tabs.length > 0 && (
          <div className="flex items-center gap-0.5 border-t border-(--color-border) px-2 py-1 overflow-x-auto">
            {status.tabs.map((tab) => {
              const isActiveTab = tab.url === currentUrl
              return (
                <button
                  key={tab.index}
                  onClick={() => send({ action: 'switch_tab', index: tab.index })}
                  className={cn(
                    'shrink-0 truncate rounded-md px-2 py-0.5 text-[10px] max-w-[140px] transition-colors',
                    isActiveTab
                      ? 'bg-(--color-accent)/10 text-(--color-accent) font-medium'
                      : 'text-(--color-text) opacity-50 hover:bg-(--bg-key) hover:opacity-80',
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
