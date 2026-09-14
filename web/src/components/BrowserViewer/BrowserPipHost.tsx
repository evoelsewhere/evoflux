/**
 * The corner preview: a page an agent opened, shown small, over the
 * conversation, while the workbench stays on whatever the person was using.
 *
 * The page is the real thing, not a screenshot — the same native view the
 * panel would host, positioned over a small card instead of a panel. Only
 * the card's chrome is DOM: the native view is an OS-level layer above this
 * document, so anything drawn *over* the page area would be invisible, and
 * every control here sits outside it.
 */

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Maximize2, Minimize2, PanelRight, X } from 'lucide-react'

import { cn } from '@/lib/utils'
import { useToastStore } from '@/stores/useToastStore'
import { useUIStore } from '@/stores/useUIStore'
import {
  FIT_DESKTOP_WIDTH,
  loadBrowserPreferences,
  subscribeBrowserPreferences,
  type BrowserPreferences,
} from './browserPreferences'
import { useDirectBrowserTabs } from './useDirectBrowserTabs'

/** Small enough to sit beside the conversation, big enough to read a layout. */
const PREVIEW_SIZES = {
  small: { width: 384, height: 240 },
  large: { width: 640, height: 400 },
} as const

interface BrowserPipHostProps {
  sessionId: string
}

export function BrowserPipHost({ sessionId }: BrowserPipHostProps) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const [preferences, setPreferences] = useState<BrowserPreferences>(loadBrowserPreferences)
  const [size, setSize] = useState<keyof typeof PREVIEW_SIZES>('small')
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

  const { width, height } = PREVIEW_SIZES[size]
  const url = browser.activeTab?.url ?? ''
  let host = 'Browser'
  try {
    host = new URL(url).host || 'Browser'
  } catch {
    // A blank or internal page keeps the generic label.
  }

  // Rendered into the document body on purpose: `fixed` is relative to the
  // nearest transformed ancestor, and this host hangs off a column that has
  // one — which put the preview in the middle of the app instead of its
  // corner.
  return createPortal((
    <div
      className="pointer-events-none fixed bottom-4 right-4 z-(--z-overlay) flex justify-end"
      style={{ width }}
    >
      <div className="pointer-events-auto w-full overflow-hidden rounded-lg border border-(--color-border-strong) bg-(--bg-card) shadow-xl">
        <div className="flex h-8 items-center gap-1 border-b border-(--color-border) px-2">
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
            label={size === 'small' ? 'Show larger' : 'Show smaller'}
            onClick={() => setSize(size === 'small' ? 'large' : 'small')}
          >
            {size === 'small' ? <Maximize2 /> : <Minimize2 />}
          </PreviewButton>
          <PreviewButton label="Close the preview" onClick={closePip}>
            <X />
          </PreviewButton>
        </div>
        {/* The native view is placed exactly over this box. */}
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
