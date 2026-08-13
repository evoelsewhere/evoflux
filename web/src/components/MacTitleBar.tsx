/**
 * MacTitleBar — native-feeling controls beside the macOS traffic lights.
 *
 * The fixed strip owns the otherwise-empty title-bar corner. Interactive
 * descendants opt out of `useTauriDrag`, while the gaps remain draggable.
 * Route headers reserve the full control width with
 * `--spacing-mac-window-controls-inset` when their content reaches this edge.
 */
import { useLocation, useRouter } from '@tanstack/react-router'
import { ChevronLeft, ChevronRight, PanelLeft } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { usePlatform } from '@/hooks/use-platform'
import { useTauriDrag } from '@/hooks/use-tauri-drag'
import { appModeForPath } from '@/lib/mode-route'
import { requestShellSidebarToggle } from '@/lib/shell-events'
import { useUIStore } from '@/stores/useUIStore'

interface HistoryBounds {
  maxIndex: number
}

const CONTROL_CLASS =
  'flex h-7 w-[26px] items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)/40 disabled:pointer-events-none disabled:opacity-35'

export function MacTitleBar() {
  const { isMacOverlay } = usePlatform()
  const dragHandlers = useTauriDrag()
  const router = useRouter()
  const location = useLocation()
  const settingsOpen = useUIStore((state) => state.settingsOpen)
  const sidebarCollapsed = useUIStore((state) => state.sidebarCollapsed)
  const currentIndex = location.state.__TSR_index ?? 0
  const boundsRef = useRef<HistoryBounds>({ maxIndex: currentIndex })
  const [maxIndex, setMaxIndex] = useState(currentIndex)
  const hasAppSidebar = appModeForPath(location.pathname) !== null && !settingsOpen

  useEffect(() => {
    boundsRef.current.maxIndex = Math.max(
      boundsRef.current.maxIndex,
      router.history.location.state.__TSR_index ?? 0,
    )

    return router.history.subscribe(({ location: nextLocation, action }) => {
      const nextIndex = nextLocation.state.__TSR_index ?? 0
      // A push from a previously visited page replaces the browser's forward
      // branch. Back/forward/go preserve the furthest entry seen this mount.
      const nextMaxIndex = action.type === 'PUSH'
        ? nextIndex
        : Math.max(boundsRef.current.maxIndex, nextIndex)
      boundsRef.current.maxIndex = nextMaxIndex
      setMaxIndex(nextMaxIndex)
    })
  }, [router])

  useEffect(() => {
    if (!isMacOverlay) return
    document.documentElement.setAttribute('data-platform', 'mac-overlay')
    return () => document.documentElement.removeAttribute('data-platform')
  }, [isMacOverlay])

  if (!isMacOverlay) return null

  const canGoBack = currentIndex > 0
  const canGoForward = currentIndex < maxIndex

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
          onClick={() => router.history.back()}
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
          onClick={() => router.history.forward()}
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
