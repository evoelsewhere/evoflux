/**
 * useWindowHistory — back/forward state for the desktop title-bar controls
 * (MacTitleBar, WindowsTitleBar), plus whether the current route has a
 * sidebar the toggle can act on.
 */
import { useLocation, useRouter } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'

import { appModeForPath } from '@/lib/mode-route'
import { useUIStore } from '@/stores/useUIStore'

export function useWindowHistory() {
  const router = useRouter()
  const location = useLocation()
  const settingsOpen = useUIStore((state) => state.settingsOpen)
  const sidebarCollapsed = useUIStore((state) => state.sidebarCollapsed)
  const currentIndex = location.state.__TSR_index ?? 0
  const boundsRef = useRef({ maxIndex: currentIndex })
  const [maxIndex, setMaxIndex] = useState(currentIndex)

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

  return {
    canGoBack: currentIndex > 0,
    canGoForward: currentIndex < maxIndex,
    back: () => router.history.back(),
    forward: () => router.history.forward(),
    hasAppSidebar: appModeForPath(location.pathname) !== null && !settingsOpen,
    sidebarCollapsed,
  }
}
