/**
 * MacTitleBar — native-feeling controls beside the macOS traffic lights.
 *
 * The fixed strip owns the otherwise-empty title-bar corner. Interactive
 * descendants opt out of `useTauriDrag`, while the gaps remain draggable.
 * Route headers reserve the full control width with
 * `--spacing-mac-window-controls-inset` when their content reaches this edge.
 */
import { ChevronLeft, ChevronRight, PanelLeft } from 'lucide-react'
import { useEffect } from 'react'

import { usePlatform } from '@/hooks/use-platform'
import { useTauriDrag } from '@/hooks/use-tauri-drag'
import { useWindowHistory } from '@/hooks/use-window-history'
import { requestShellSidebarToggle } from '@/lib/shell-events'

const CONTROL_CLASS =
  'flex h-7 w-[26px] items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)/40 disabled:pointer-events-none disabled:opacity-35'

export function MacTitleBar() {
  const { isMacOverlay } = usePlatform()
  const dragHandlers = useTauriDrag()
  const { canGoBack, canGoForward, back, forward, hasAppSidebar, sidebarCollapsed } =
    useWindowHistory()

  useEffect(() => {
    if (!isMacOverlay) return
    document.documentElement.setAttribute('data-platform', 'mac-overlay')
    return () => document.documentElement.removeAttribute('data-platform')
  }, [isMacOverlay])

  if (!isMacOverlay) return null

  return (
    <div
      {...dragHandlers}
      className="fixed left-0 top-0 z-(--z-overlay) h-10 w-(--spacing-mac-window-controls-inset) select-none"
      aria-label="Window navigation"
    >
      <div className="absolute left-(--spacing-mac-traffic-inset) pl-2 top-[5px] flex h-7 items-center">
        <button
          type="button"
          onClick={requestShellSidebarToggle}
          disabled={!hasAppSidebar}
          aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!sidebarCollapsed}
          title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className={CONTROL_CLASS}
          data-no-drag
        >
          <PanelLeft size={16} strokeWidth={1.7} aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={back}
          disabled={!canGoBack}
          aria-label="Back"
          title="Back"
          className={CONTROL_CLASS}
          data-no-drag
        >
          <ChevronLeft size={16} strokeWidth={1.8} aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={forward}
          disabled={!canGoForward}
          aria-label="Forward"
          title="Forward"
          className={CONTROL_CLASS}
          data-no-drag
        >
          <ChevronRight size={16} strokeWidth={1.8} aria-hidden="true" />
        </button>
      </div>
    </div>
  )
}
