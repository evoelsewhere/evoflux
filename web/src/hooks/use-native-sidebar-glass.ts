import { useEffect } from 'react'

import { usePlatform } from '@/hooks/use-platform'

let activeGlassSurfaces = 0

/** Keep the native macOS material enabled while any sidebar surface is live. */
export function useNativeSidebarGlass(): void {
  const { isTauri, os } = usePlatform()
  const active = isTauri && os === 'macos'

  useEffect(() => {
    if (!active) return

    activeGlassSurfaces += 1
    document.documentElement.dataset.nativeSidebarGlass = 'true'

    return () => {
      activeGlassSurfaces = Math.max(0, activeGlassSurfaces - 1)
      if (activeGlassSurfaces === 0) {
        delete document.documentElement.dataset.nativeSidebarGlass
      }
    }
  }, [active])
}
