import { useEffect } from 'react'
import { getCurrentWindow } from '@tauri-apps/api/window'

import { usePlatform } from '@/hooks/use-platform'
import { useThemePreference } from '@/hooks/useThemePreference'

let activeGlassSurfaces = 0

/** Keep the native desktop material enabled while any sidebar surface is live. */
export function useNativeSidebarGlass(): void {
  const { isTauri, os } = usePlatform()
  const { preference } = useThemePreference()
  const active = isTauri && (os === 'macos' || os === 'windows')

  useEffect(() => {
    if (!active) return

    // Native materials read the window appearance, which can differ from an
    // explicit EvoFlux preference. Rust remains the sole effects owner.
    void getCurrentWindow()
      .setTheme(preference === 'system' ? null : preference)
      .catch(() => {})
  }, [active, preference])

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
