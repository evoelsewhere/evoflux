import { useEffect } from 'react'
import { Effect, getCurrentWindow } from '@tauri-apps/api/window'

import { usePlatform } from '@/hooks/use-platform'
import { useThemePreference } from '@/hooks/useThemePreference'

let activeGlassSurfaces = 0

/** Keep the native desktop material enabled while any sidebar surface is live. */
export function useNativeSidebarGlass(): void {
  const { isTauri, os } = usePlatform()
  const { preference, resolved } = useThemePreference()
  const active = isTauri && (os === 'macos' || os === 'windows')

  useEffect(() => {
    if (!active) return

    const syncNativeAppearance = async () => {
      const window = getCurrentWindow()
      // Semantic macOS materials and Windows DWM both read the native window
      // appearance, which can differ from EvoFlux's explicit preference.
      await window.setTheme(preference === 'system' ? null : preference)

      if (os === 'windows') {
        await window.setEffects({
          effects: [Effect.Acrylic],
          color: resolved === 'dark'
            ? [35, 34, 32, 110]
            : [250, 250, 250, 110],
        })
      }
    }

    void syncNativeAppearance().catch(() => {})
  }, [active, os, preference, resolved])

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
