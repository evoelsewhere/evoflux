/**
 * The corner preview: a page an agent opened, shown small, over the
 * conversation, while the workbench stays on whatever the person was using.
 *
 * The page is the real thing, not a screenshot — the same native view the
 * panel would host, positioned over a small card instead of a panel. Only
 * the card's chrome is DOM: the native view is an OS-level layer above this
 * document, so anything drawn *over* the page area would be invisible, and
 * every control here sits outside it. That is also why dragging works from
 * the header rather than the page: a pointer over the page is over the
 * native view, and this document never sees it.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { GripVertical, Maximize2, Minimize2, PanelRight, X } from 'lucide-react'

import { cn } from '@/lib/utils'
import { useToastStore } from '@/stores/useToastStore'
import { useUIStore } from '@/stores/useUIStore'
import {
  FIT_DESKTOP_WIDTH,
  loadBrowserPreferences,
  subscribeBrowserPreferences,
  type BrowserPreferences,
} from './browserPreferences'
import {
  clampPreviewPlacement,
  HEADER_HEIGHT,
  loadPreviewPlacement,
  PREVIEW_SIZES,
  savePreviewPlacement,
  type PreviewPlacement,
} from './browserPreviewPlacement'
import { useDirectBrowserTabs } from './useDirectBrowserTabs'

interface BrowserPipHostProps {
  sessionId: string
}

export function BrowserPipHost({ sessionId }: BrowserPipHostProps) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const [preferences, setPreferences] = useState<BrowserPreferences>(loadBrowserPreferences)
  const [placement, setPlacement] = useState<PreviewPlacement>(loadPreviewPlacement)
  const [dragging, setDragging] = useState(false)
  // Incremented whenever the card moves: the native view is positioned from
  // this box's rectangle, and moving a box fires no observer.
  const [syncKey, setSyncKey] = useState(0)
  const pushToast = useToastStore((state) => state.push)
  const closePip = useUIStore((state) => state.closeBrowserPip)
  const openWorkbenchTool = useUIStore((state) => state.openWorkbenchTool)

  useEffect(() => subscribeBrowserPreferences(setPreferences), [])

  const browser = useDirectBrowserTabs({
    sessionId,
    instanceId: 'preview',
    viewportRef,
    enabled: preferences.enabled,
    visible: true,
    bridgeEnabled: true,
    singleTab: true,
    zoom: preferences.defaultZoom,
    // Lay the page out as a desktop and shrink the whole thing to fit. At
    // this size that is unreadable as text and perfectly readable as shape,
    // which is what watching an agent work needs.
    fitWidth: FIT_DESKTOP_WIDTH,
    minFitScale: 0.2,
    syncKey,
    devtools: preferences.developerTools,
    profileMode: preferences.profileMode,
    onError: (message) => pushToast({
      tone: 'error',
      title: 'Browser action failed',
      description: message,
    }),
    // A popup is a page in its own right, and the panel is where a page
    // someone has to read belongs.
    onRequestNewTab: (url) => openWorkbenchTool('browser', { initialUrl: url }),
    onCloseSurface: closePip,
  })

  const move = useCallback((next: PreviewPlacement) => {
    const clamped = clampPreviewPlacement(next)
    setPlacement(clamped)
    savePreviewPlacement(clamped)
    setSyncKey((current) => current + 1)
  }, [])

  // A window that shrank can leave the card off screen, where nothing can
  // reach its header to drag it back.
  useEffect(() => {
    const onResize = () => setPlacement((current) => {
      const clamped = clampPreviewPlacement(current)
      setSyncKey((key) => key + 1)
      return clamped
    })
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const startDrag = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return
    event.preventDefault()
    const origin = { x: event.clientX, y: event.clientY }
    const start = placement
    setDragging(true)
    const onMove = (moveEvent: PointerEvent) => {
      move({
        size: start.size,
        x: start.x + (moveEvent.clientX - origin.x),
        y: start.y + (moveEvent.clientY - origin.y),
      })
    }
    const onUp = () => {
      setDragging(false)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }, [move, placement])

  const { width, height } = PREVIEW_SIZES[placement.size]
  const url = browser.activeTab?.url ?? ''
  let host = 'Browser'
  try {
    host = new URL(url).host || 'Browser'
  } catch {
    // A blank or internal page keeps the generic label.
  }

  // Rendered into the document body on purpose: `fixed` is relative to the
  // nearest transformed ancestor, and this host hangs off a column that has
  // one — which put the preview in the middle of the app instead of a corner.
  return createPortal((
    <div
      className="fixed z-(--z-overlay)"
      style={{ left: placement.x, top: placement.y, width }}
    >
      <div
        className={cn(
          'w-full overflow-hidden rounded-lg border bg-(--bg-card) shadow-xl',
          dragging
            ? 'border-(--color-accent)/60 shadow-2xl'
            : 'border-(--color-border-strong)',
        )}
      >
        <div
          onPointerDown={startDrag}
          className={cn(
            'flex items-center gap-1 border-b border-(--color-border) px-1.5',
            dragging ? 'cursor-grabbing' : 'cursor-grab',
          )}
          style={{ height: HEADER_HEIGHT }}
        >
          <GripVertical
            size={13}
            aria-hidden
            className="shrink-0 text-(--color-text-subtle)"
          />
          <span className="min-w-0 flex-1 truncate text-[11px] text-(--color-text-muted)">
            {browser.loading ? 'Loading…' : host}
          </span>
          <PreviewButton
            label="Open in the browser panel"
            onClick={() => {
              openWorkbenchTool('browser', { initialUrl: url || undefined })
              closePip()
            }}
          >
            <PanelRight />
          </PreviewButton>
          <PreviewButton
            label={placement.size === 'small' ? 'Show larger' : 'Show smaller'}
            onClick={() => move({
              ...placement,
              size: placement.size === 'small' ? 'large' : 'small',
            })}
          >
            {placement.size === 'small' ? <Maximize2 /> : <Minimize2 />}
          </PreviewButton>
          <PreviewButton label="Close the preview" onClick={closePip}>
            <X />
          </PreviewButton>
        </div>
        {/* The native view is placed exactly over this box, and the page
            inside it takes clicks and scrolling of its own. */}
        <div ref={viewportRef} className="w-full bg-white" style={{ height }} />
      </div>
    </div>
  ), document.body)
}

function PreviewButton({
  label,
  children,
  onClick,
}: {
  label: string
  children: React.ReactNode
  onClick: () => void
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
      )}
    >
      {children}
    </button>
  )
}
