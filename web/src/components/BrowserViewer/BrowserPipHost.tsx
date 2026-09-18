/**
 * The corner preview: a page an agent opened, shown small, over the
 * conversation, while the workbench stays on whatever the person was using.
 *
 * The page is the real thing, not a screenshot — the same native view the
 * panel would host, positioned over a small card instead of a panel. Only
 * the card's chrome is DOM: the native view is an OS-level layer above this
 * document, so anything drawn *over* the page area would be invisible, and
 * every control here sits outside it. That is also why dragging works from
 * the header and resizing from the strip below the page: a pointer over the
 * page is over the native view, and this document never sees it.
 *
 * The one exception is what this file calls an overlay. Hiding the native
 * view hands the page area back to DOM, which is the only way to ask a
 * question about a page inside the card — and the only way to say anything
 * at all about a page too small to read at this size.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  CircleAlert,
  GripVertical,
  Maximize2,
  Minimize2,
  PanelRight,
  X,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
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
  FOOTER_HEIGHT,
  HEADER_HEIGHT,
  loadPreviewPlacement,
  nextPreviewSize,
  PREVIEW_SIZES,
  stackPreviewPlacement,
  savePreviewPlacement,
  type PreviewPlacement,
} from './browserPreviewPlacement'
import { isBrowserNewTab, useDirectBrowserTabs } from './useDirectBrowserTabs'

interface BrowserPipHostProps {
  sessionId: string
  stackDepth: number
  stackOrder: number
}

export function BrowserPipHost({ sessionId, stackDepth, stackOrder }: BrowserPipHostProps) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const [preferences, setPreferences] = useState<BrowserPreferences>(loadBrowserPreferences)
  const [placement, setPlacement] = useState<PreviewPlacement>(loadPreviewPlacement)
  const [gesture, setGesture] = useState<'move' | 'resize' | null>(null)
  // Incremented whenever the card moves: the native view is positioned from
  // this box's rectangle, and moving a box fires no observer.
  const [syncKey, setSyncKey] = useState(0)
  const pushToast = useToastStore((state) => state.push)
  const closePipForSession = useUIStore((state) => state.closeBrowserPip)
  const focusPip = useUIStore((state) => state.focusBrowserPip)
  const closePip = useCallback(
    () => closePipForSession(sessionId),
    [closePipForSession, sessionId],
  )
  // A new tab every time, not the last browser tab reused: the pages this
  // opens are a popup and a handed-over page, and both are specific pages
  // that would be silently dropped by activating a tab already showing
  // something else.
  const createWorkbenchTab = useUIStore((state) => state.createWorkbenchTab)

  useEffect(() => subscribeBrowserPreferences(setPreferences), [])

  // Set from the overlay resolved below, which needs the browser that needs
  // this — so it lands a render later, the same way the panel handles its
  // own error card. Starting hidden is right: there is no page yet.
  const [pageHidden, setPageHidden] = useState(true)

  const browser = useDirectBrowserTabs({
    sessionId,
    instanceId: 'preview',
    viewportRef,
    enabled: preferences.enabled,
    // A hidden page is how the card says anything: an overlay is DOM, and
    // DOM under a native view cannot be seen.
    visible: !pageHidden,
    bridgeEnabled: true,
    singleTab: true,
    zoom: preferences.defaultZoom,
    // Lay the page out as a desktop and shrink the whole thing to fit. At
    // this size that is unreadable as text and perfectly readable as shape,
    // which is what watching an agent work needs.
    fitWidth: FIT_DESKTOP_WIDTH,
    minFitScale: 0.2,
    syncKey: syncKey + stackDepth,
    devtools: preferences.developerTools,
    profileMode: preferences.profileMode,
    onError: (message) => pushToast({
      tone: 'error',
      title: 'Browser action failed',
      description: message,
    }),
    // A popup is a page in its own right, and the panel is where a page
    // someone has to read belongs.
    onRequestNewTab: (popupUrl) => createWorkbenchTab('browser', {
      initialUrl: popupUrl,
      title: 'New tab',
    }),
    onCloseSurface: closePip,
  })

  const url = browser.activeTab?.url ?? ''
  const overlay: OverlayKind | null = !preferences.enabled
    ? 'disabled'
    : browser.pageDialog
      ? 'dialog'
      : browser.pagePermission
        ? 'permission'
        : browser.pageError
          ? 'error'
          : !browser.activeTab
            ? 'starting'
            // The engine's own new-tab page is a full desktop layout scaled
            // to a fifth of its size: a speck of a globe and text nobody can
            // read. Say what it means instead of showing it.
            : isBrowserNewTab(url)
              ? 'blank'
              : null
  // Adjusted during render rather than in an effect: the overlay and the
  // native view's visibility must flip in the same commit, or one frame
  // shows both (or neither) — the same rule the panel follows.
  if ((overlay !== null) !== pageHidden) setPageHidden(overlay !== null)

  /**
   * Move this page into the workbench — the page, not its address. The
   * panel tab is created with an id chosen here so the WebView being let go
   * of can be offered to that tab and no other; the panel then adopts it
   * instead of loading the same URL into a WebView of its own, which is
   * what used to happen and what cost the page everything it had.
   */
  const openInPanel = useCallback(() => {
    const claimant = `browser-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    const moved = browser.activeTabId
      ? browser.releaseTab(browser.activeTabId, claimant)
      : false
    createWorkbenchTab('browser', {
      id: claimant,
      // Only a fallback: an adopted page is already showing this.
      initialUrl: url || undefined,
      title: moved ? undefined : 'New tab',
    })
    closePip()
  }, [browser, closePip, createWorkbenchTab, url])

  const place = useCallback((next: PreviewPlacement, persist = false) => {
    const clamped = clampPreviewPlacement(next)
    setPlacement(clamped)
    setSyncKey((current) => current + 1)
    // Saving per pointer event writes to storage a hundred times a drag; the
    // only placement worth keeping is the one let go of.
    if (persist) savePreviewPlacement(clamped)
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

  const startGesture = useCallback((
    kind: 'move' | 'resize',
    event: React.PointerEvent<HTMLDivElement>,
  ) => {
    if (event.button !== 0) return
    event.preventDefault()
    const origin = { x: event.clientX, y: event.clientY }
    const start = placement
    setGesture(kind)
    let latest = start
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
      // A pointer that crosses a native WebView stops being this document's
      // to hear: the OS hands it to the page instead, and neither the moves
      // nor the release ever arrive. Without these the card would stay stuck
      // to a pointer that is no longer dragging it.
      window.removeEventListener('pointercancel', end)
      window.removeEventListener('blur', end)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', end)
    window.addEventListener('pointercancel', end)
    window.addEventListener('blur', end)
  }, [place, placement])

  const stackedPlacement = stackPreviewPlacement(placement, stackDepth)
  const { width, height } = stackedPlacement
  const preset = nextPreviewSize(placement)
  const growing = preset.width === PREVIEW_SIZES.large.width
  let host = 'Browser'
  try {
    host = new URL(url).host || 'Browser'
  } catch {
    // A blank or internal page keeps the generic label.
  }
  const label = browser.loading
    ? 'Loading…'
    : overlay === 'blank' || overlay === 'starting'
      ? 'New tab'
      : host

  // Rendered into the document body on purpose: `fixed` is relative to the
  // nearest transformed ancestor, and this host hangs off a column that has
  // one — which put the preview in the middle of the app instead of a corner.
  return createPortal((
    <div
      className="fixed z-(--z-overlay)"
      onPointerDownCapture={() => focusPip(sessionId)}
      style={{
        left: stackedPlacement.x,
        top: stackedPlacement.y,
        width,
        zIndex: 100 + stackOrder,
      }}
    >
      <div
        className={cn(
          'w-full overflow-hidden rounded-lg border bg-(--bg-card) shadow-xl',
          gesture
            ? 'border-(--color-accent)/60 shadow-2xl'
            : 'border-(--color-border-strong)',
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
          <GripVertical
            size={13}
            aria-hidden
            className="shrink-0 text-(--color-text-subtle)"
          />
          <span className="min-w-0 flex-1 truncate text-[11px] text-(--color-text-muted)">
            {label}
          </span>
          <PreviewButton label="Open in the browser panel" onClick={openInPanel}>
            <PanelRight />
          </PreviewButton>
          <PreviewButton
            label={growing ? 'Show larger' : 'Show smaller'}
            onClick={() => place({ ...placement, ...preset }, true)}
          >
            {growing ? <Maximize2 /> : <Minimize2 />}
          </PreviewButton>
          <PreviewButton label="Close the preview" onClick={closePip}>
            <X />
          </PreviewButton>
        </div>
        {/* The native view is placed exactly over this box, and the page
            inside it takes clicks and scrolling of its own — except while an
            overlay has it hidden, when this box is ordinary DOM again. */}
        <div
          ref={viewportRef}
          className="relative w-full bg-(--bg-page)"
          style={{ height }}
        >
          {overlay && (
            <PreviewOverlay kind={overlay} browser={browser} onOpenPanel={openInPanel} />
          )}
        </div>
        <div
          onPointerDown={(event) => startGesture('resize', event)}
          title="Resize the preview"
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

type OverlayKind = 'disabled' | 'dialog' | 'permission' | 'error' | 'starting' | 'blank'

/**
 * What the card shows instead of the page.
 *
 * A dialog is the reason this exists: a page that calls `confirm()` is
 * stopped until someone answers, and the panel is where that answer used to
 * have to come from — so a preview showing such a page went blank and stayed
 * blank, with no way to tell that anything was being asked.
 */
function PreviewOverlay({
  kind,
  browser,
  onOpenPanel,
}: {
  kind: OverlayKind
  browser: ReturnType<typeof useDirectBrowserTabs>
  onOpenPanel: () => void
}) {
  const dialog = browser.pageDialog
  const permission = browser.pagePermission
  const error = browser.pageError

  if (kind === 'dialog' && dialog) {
    return (
      <OverlayFrame tone="attention" title={`Page ${dialog.type}`}>
        <p className="line-clamp-3 whitespace-pre-wrap break-words text-[11px] leading-4 text-(--color-text)">
          {dialog.message || '(This page opened an empty dialog.)'}
        </p>
        <OverlayActions>
          <Button type="button" size="xs" onClick={browser.dismissPageDialog}>
            Continue
          </Button>
        </OverlayActions>
      </OverlayFrame>
    )
  }

  if (kind === 'permission' && permission) {
    return (
      <OverlayFrame tone="attention" title={`This page wants ${permission.kind}`}>
        <OverlayActions>
          <Button
            type="button"
            size="xs"
            variant="ghost"
            onClick={() => void browser.resolvePagePermission(false)}
          >
            Block
          </Button>
          <Button
            type="button"
            size="xs"
            onClick={() => void browser.resolvePagePermission(true)}
          >
            Allow
          </Button>
        </OverlayActions>
      </OverlayFrame>
    )
  }

  if (kind === 'error' && error) {
    return (
      <OverlayFrame tone="attention" title="This page did not load">
        <p className="truncate text-[11px] text-(--color-text-muted)">{error.url}</p>
        {error.detail && (
          <p className="line-clamp-2 text-[11px] leading-4 text-(--color-text-muted)">
            {error.detail}
          </p>
        )}
        <OverlayActions>
          <Button type="button" size="xs" variant="ghost" onClick={onOpenPanel}>
            Open in the panel
          </Button>
        </OverlayActions>
      </OverlayFrame>
    )
  }

  return (
    <OverlayFrame
      tone="quiet"
      title={kind === 'disabled' ? 'The in-app browser is off' : 'Nothing open yet'}
    >
      <p className="text-[11px] leading-4 text-(--color-text-muted)">
        {kind === 'disabled'
          ? 'Turn it on in the browser panel’s settings to watch an agent browse here.'
          : kind === 'starting'
            ? 'Opening a page…'
            : 'The page an agent opens will appear here.'}
      </p>
    </OverlayFrame>
  )
}

function OverlayFrame({
  tone,
  title,
  children,
}: {
  tone: 'attention' | 'quiet'
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="absolute inset-0 flex flex-col justify-center gap-1.5 overflow-hidden px-3">
      <div className="flex items-center gap-1.5">
        {tone === 'attention' && (
          <CircleAlert size={13} aria-hidden className="shrink-0 text-(--color-primary)" />
        )}
        <span className="truncate text-xs font-semibold text-(--color-text)">{title}</span>
      </div>
      {children}
    </div>
  )
}

function OverlayActions({ children }: { children: React.ReactNode }) {
  return <div className="flex items-center justify-end gap-1.5 pt-0.5">{children}</div>
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
