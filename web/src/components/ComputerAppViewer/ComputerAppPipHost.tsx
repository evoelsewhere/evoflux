/**
 * The corner preview for Computer App Control: the one desktop app an agent
 * is driving, shown live over the conversation with a virtual cursor.
 *
 * Unlike the browser preview this card is ordinary DOM all the way down. The
 * app is not embedded — it stays a real window wherever it is on the desktop,
 * possibly behind others — so the card shows frames captured from it and can
 * draw the agent's cursor over them.
 *
 * The card is also the user's control: Stop revokes control (and interrupts
 * the turn), Close detaches, and the agent may only act while an app is
 * attached, which is exactly while this card is open.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import {
  AppWindow,
  ExternalLink,
  GripVertical,
  Hand,
  Maximize2,
  Minimize2,
  Play,
  X,
} from 'lucide-react'

import { postComputerCardClosed, postTeamChat } from '@/api/client/team'
import { Button } from '@/components/ui/button'
import {
  clampPreviewPlacement,
  FOOTER_HEIGHT,
  HEADER_HEIGHT,
  loadPreviewPlacement,
  nextPreviewSize,
  PREVIEW_SIZES,
  savePreviewPlacement,
  stackPreviewPlacement,
  type PreviewPlacement,
} from '@/components/BrowserViewer/browserPreviewPlacement'
import { useI18n } from '@/i18n'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { cn } from '@/lib/utils'
import { useToastStore } from '@/stores/useToastStore'
import { useUIStore } from '@/stores/useUIStore'
import { AgentCursorOverlay, type AgentPointer, type PointerPhase } from './AgentCursorOverlay'
import { runComputerAppCommand } from './computerAppBridge'

const PLACEMENT_KEY = STORAGE_KEYS.computerApp.previewPlacement
/** Frames per second while the agent is driving, and while it is quiet. */
const ACTIVE_FRAME_MS = 150
const IDLE_FRAME_MS = 600
const HIDDEN_FRAME_MS = 1500
/** How long after the last pointer event the frame keeps glowing. */
const ACTIVE_WINDOW_MS = 4000

interface ComputerFrame {
  attached: boolean
  stopped?: boolean
  closed?: boolean
  minimized?: boolean
  dialog?: boolean
  app?: string
  title?: string
  width?: number
  height?: number
  media_type?: string
  data?: string
}

interface PointerEventPayload {
  sessionId: string
  x: number
  y: number
  phase: PointerPhase
}

export function ComputerAppPipHost({
  sessionId,
  stackDepth,
  stackOrder,
}: {
  sessionId: string
  stackDepth: number
  stackOrder: number
}) {
  const { t } = useI18n()
  const viewportRef = useRef<HTMLDivElement>(null)
  const [placement, setPlacement] = useState<PreviewPlacement>(
    () => loadPreviewPlacement(PLACEMENT_KEY, 1),
  )
  const [gesture, setGesture] = useState<'move' | 'resize' | null>(null)
  const [frame, setFrame] = useState<ComputerFrame | null>(null)
  const [frameError, setFrameError] = useState<string | null>(null)
  const [pointer, setPointer] = useState<AgentPointer | null>(null)
  const [lastActivity, setLastActivity] = useState(0)
  const [now, setNow] = useState(() => Date.now())
  const [box, setBox] = useState({ width: placement.width, height: placement.height })
  const pushToast = useToastStore((state) => state.push)
  const closePip = useUIStore((state) => state.closeComputerPip)
  const focusPip = useUIStore((state) => state.focusComputerPip)
  const active = now - lastActivity < ACTIVE_WINDOW_MS
  // Read by the polling loop, which must not restart on every pointer event.
  const lastActivityRef = useRef(0)

  // Poll frames: fast while the agent works, slowly while it is quiet or
  // the app window is hidden, and never two requests at once.
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | null = null
    const tick = async () => {
      const width = viewportRef.current?.clientWidth ?? placement.width
      const maxWidth = Math.round(width * Math.min(window.devicePixelRatio || 1, 2))
      let delay = IDLE_FRAME_MS
      try {
        const next = await invoke<ComputerFrame>('app_computer_frame', { sessionId, maxWidth })
        if (!alive) return
        setFrame(next)
        setFrameError(null)
        if (next.attached && next.data) {
          delay = Date.now() - lastActivityRef.current < ACTIVE_WINDOW_MS
            ? ACTIVE_FRAME_MS
            : IDLE_FRAME_MS
        }
      } catch (error) {
        if (!alive) return
        setFrameError(error instanceof Error ? error.message : String(error))
      }
      if (document.hidden) delay = HIDDEN_FRAME_MS
      setNow(Date.now())
      timer = setTimeout(() => void tick(), delay)
    }
    void tick()
    return () => {
      alive = false
      if (timer) clearTimeout(timer)
    }
    // The viewport width is read per tick; restarting on resize would only
    // drop a frame.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  useEffect(() => {
    let unlisten: (() => void) | null = null
    let seq = 0
    let disposed = false
    void listen<PointerEventPayload>('computer-app:pointer', (event) => {
      const payload = event.payload
      if (payload.sessionId !== sessionId) return
      seq += 1
      lastActivityRef.current = Date.now()
      setLastActivity(lastActivityRef.current)
      setPointer({ x: payload.x, y: payload.y, phase: payload.phase, seq })
    }).then((dispose) => {
      if (disposed) dispose()
      else unlisten = dispose
    })
    return () => {
      disposed = true
      unlisten?.()
    }
  }, [sessionId])

  // Track the picture area so the cursor maps onto the letterboxed frame.
  useEffect(() => {
    const element = viewportRef.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => {
      setBox({ width: entry.contentRect.width, height: entry.contentRect.height })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const place = useCallback((next: PreviewPlacement, persist = false) => {
    const clamped = clampPreviewPlacement(next)
    setPlacement(clamped)
    if (persist) savePreviewPlacement(clamped, PLACEMENT_KEY)
  }, [])

  useEffect(() => {
    const onResize = () => setPlacement((current) => clampPreviewPlacement(current))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const startGesture = useCallback((
    kind: 'move' | 'resize',
    event: React.PointerEvent<HTMLDivElement>,
  ) => {
    if (event.button !== 0) return
    event.preventDefault()
    const origin = { x: event.clientX, y: event.clientY }
    const start = placement
    let latest = start
    setGesture(kind)
    const onMove = (moveEvent: PointerEvent) => {
      const dx = moveEvent.clientX - origin.x
      const dy = moveEvent.clientY - origin.y
      latest = kind === 'move'
        ? { ...start, x: start.x + dx, y: start.y + dy }
        : { ...start, width: start.width + dx, height: start.height + dy }
      place(latest)
    }
    const end = () => {
      setGesture(null)
      place(latest, true)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', end)
      window.removeEventListener('pointercancel', end)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', end)
    window.addEventListener('pointercancel', end)
  }, [place, placement])

  const reportFailure = useCallback((title: string, error: unknown) => {
    pushToast({
      tone: 'error',
      title,
      description: error instanceof Error ? error.message : String(error),
    })
  }, [pushToast])

  /** Revoke control and stop the turn that was using it. */
  const stopControl = useCallback(async () => {
    try {
      await invoke('app_computer_stop', { sessionId })
      setPointer(null)
      await postTeamChat(null, sessionId, true)
    } catch (error) {
      reportFailure(t('Could not stop app control'), error)
    }
  }, [reportFailure, sessionId, t])

  const allowAgain = useCallback(async () => {
    try {
      await invoke('app_computer_resume', { sessionId })
    } catch (error) {
      reportFailure(t('Could not allow app control'), error)
    }
  }, [reportFailure, sessionId, t])

  const revealApp = useCallback(async () => {
    try {
      await invoke('app_computer_reveal', { sessionId })
    } catch (error) {
      reportFailure(t('Could not show the app'), error)
    }
  }, [reportFailure, sessionId, t])

  /**
   * Closing the card ends control: the agent never drives an app unwatched,
   * and may not attach one again (reopening the card) until its turn ends.
   */
  const closeCard = useCallback(() => {
    void postComputerCardClosed(sessionId).catch(() => undefined)
    void runComputerAppCommand(sessionId, 'detach', {})
    closePip(sessionId)
  }, [closePip, sessionId])

  const stacked = stackPreviewPlacement(placement, stackDepth)
  const preset = nextPreviewSize(placement)
  const growing = preset.width === PREVIEW_SIZES.large.width
  const attached = Boolean(frame?.attached)
  const stopped = Boolean(frame?.stopped)
  const picture = attached && frame?.data && !frame.closed && !frame.minimized
    ? `data:${frame.media_type ?? 'image/jpeg'};base64,${frame.data}`
    : null
  const content = { width: frame?.width ?? 16, height: frame?.height ?? 10 }
  const label = attached
    ? [frame?.app, frame?.title].filter(Boolean).join(' — ')
    : t('Computer App Control')

  const notice = stopped
    ? { title: t('You stopped app control'), body: t('The agent cannot use apps in this chat until you allow it again.') }
    : frameError && !frame
      ? { title: t('App preview unavailable'), body: frameError }
      : !attached
        ? { title: t('No app attached'), body: t('The app an agent controls will appear here.') }
        : frame?.closed
          ? { title: t('The app window was closed'), body: t('The agent needs to attach to an app again.') }
          : frame?.minimized
            ? { title: t('The app is minimized'), body: t('It is restored without taking focus when the agent acts again.') }
            // The last good frame would otherwise stay up as if it were live.
            : frameError
              ? { title: t('Preview paused'), body: frameError }
              : null

  return createPortal((
    <div
      className="fixed z-(--z-overlay)"
      onPointerDownCapture={() => focusPip(sessionId)}
      style={{ left: stacked.x, top: stacked.y, width: stacked.width, zIndex: 100 + stackOrder }}
    >
      <div
        className={cn(
          'w-full overflow-hidden rounded-lg border bg-(--bg-card) shadow-xl',
          gesture ? 'border-(--color-accent)/60 shadow-2xl' : 'border-(--color-border-strong)',
        )}
      >
        <div
          onPointerDown={(event) => startGesture('move', event)}
          className={cn(
            'flex touch-none items-center gap-1 border-b border-(--color-border) px-1.5',
            gesture === 'move' ? 'cursor-grabbing' : 'cursor-grab',
          )}
          style={{ height: HEADER_HEIGHT }}
        >
          <GripVertical size={13} aria-hidden className="shrink-0 text-(--color-text-subtle)" />
          <AppWindow size={12} aria-hidden className="shrink-0 text-(--color-text-muted)" />
          <span className="min-w-0 flex-1 truncate text-[11px] text-(--color-text-muted)" data-i18n-ignore={attached || undefined}>
            {label}
          </span>
          {attached && !stopped && (
            <CardButton label={t('Show the app')} onClick={() => void revealApp()}>
              <ExternalLink />
            </CardButton>
          )}
          <CardButton
            label={growing ? t('Show larger') : t('Show smaller')}
            onClick={() => place({ ...placement, ...preset }, true)}
          >
            {growing ? <Maximize2 /> : <Minimize2 />}
          </CardButton>
          {stopped ? (
            <CardButton label={t('Allow app control again')} onClick={() => void allowAgain()}>
              <Play />
            </CardButton>
          ) : (
            <CardButton label={t('Stop app control')} tone="danger" onClick={() => void stopControl()}>
              <Hand />
            </CardButton>
          )}
          <CardButton label={t('Close and end app control')} onClick={closeCard}>
            <X />
          </CardButton>
        </div>
        <div
          ref={viewportRef}
          className="relative w-full select-none overflow-hidden bg-black/90"
          style={{ height: stacked.height }}
        >
          {picture && (
            <img
              src={picture}
              alt=""
              draggable={false}
              className="absolute inset-0 h-full w-full object-contain"
            />
          )}
          {picture && !stopped && !frameError && (
            <AgentCursorOverlay
              box={box}
              content={content}
              pointer={pointer}
              active={active}
            />
          )}
          {notice && (
            <div className="absolute inset-0 flex flex-col justify-center gap-1.5 bg-(--bg-page)/90 px-3">
              <span className="truncate text-xs font-semibold text-(--color-text)">{notice.title}</span>
              <p className="line-clamp-3 text-[11px] leading-4 text-(--color-text-muted)">{notice.body}</p>
              {stopped && (
                <div className="flex justify-end gap-1.5 pt-0.5">
                  <Button type="button" size="xs" variant="ghost" onClick={closeCard}>
                    {t('Close')}
                  </Button>
                  <Button type="button" size="xs" onClick={() => void allowAgain()}>
                    {t('Allow again')}
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
        <div
          onPointerDown={(event) => startGesture('resize', event)}
          title={t('Resize the preview')}
          className={cn(
            'flex touch-none cursor-nwse-resize items-center justify-end gap-[3px] border-t',
            'border-(--color-border) px-1.5',
            gesture === 'resize' && 'bg-(--color-accent)/10',
          )}
          style={{ height: FOOTER_HEIGHT }}
        >
          <span className="h-[3px] w-[3px] rounded-full bg-(--color-text-subtle)" />
          <span className="h-[3px] w-[3px] rounded-full bg-(--color-text-subtle)" />
          <span className="h-[3px] w-[3px] rounded-full bg-(--color-text-subtle)" />
        </div>
      </div>
    </div>
  ), document.body)
}

function CardButton({
  label,
  children,
  onClick,
  tone,
}: {
  label: string
  children: React.ReactNode
  onClick: () => void
  tone?: 'danger'
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      // The header is a drag surface; a press on a button is not a drag.
      onPointerDown={(event) => event.stopPropagation()}
      onClick={onClick}
      className={cn(
        'flex size-6 shrink-0 items-center justify-center rounded text-(--color-text-muted)',
        'transition-colors hover:bg-(--bg-key) hover:text-(--color-text) [&_svg]:size-3.5',
        tone === 'danger' && 'hover:text-(--color-error)',
      )}
    >
      {children}
    </button>
  )
}
