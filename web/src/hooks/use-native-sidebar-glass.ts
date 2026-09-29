import { useEffect, useLayoutEffect } from 'react'
import { getCurrentWindow } from '@tauri-apps/api/window'

import { usePlatform } from '@/hooks/use-platform'
import { useThemePreference } from '@/hooks/useThemePreference'

let activeGlassSurfaces = 0

interface UAHighEntropy {
  getHighEntropyValues?: (hints: string[]) => Promise<{ platformVersion?: string }>
}

let preWindows11: Promise<boolean> | null = null

/**
 * Whether this is a Windows build older than Windows 11, where Rust falls back
 * from Mica to Acrylic. UA-CH reports Windows 11 as platformVersion 13 or
 * higher. Cached because the answer cannot change while the app runs.
 */
function isPreWindows11(): Promise<boolean> {
  if (preWindows11) return preWindows11
  const uaData = (navigator as unknown as { userAgentData?: UAHighEntropy }).userAgentData
  preWindows11 = uaData?.getHighEntropyValues
    ? uaData
        .getHighEntropyValues(['platformVersion'])
        .then(({ platformVersion }) => {
          const major = Number.parseInt(platformVersion?.split('.')[0] ?? '', 10)
          return Number.isFinite(major) && major < 13
        })
        .catch(() => false)
    : Promise.resolve(false)
  return preWindows11
}

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

  useLayoutEffect(() => {
    if (!active) return

    const root = document.documentElement
    activeGlassSurfaces += 1
    root.dataset.nativeSidebarGlass = os

    // Windows 10 Acrylic is untinted and ignores the window theme, so the
    // stylesheet has to supply the theme surface itself (see index.css).
    if (os === 'windows') {
      void isPreWindows11().then((acrylic) => {
        if (acrylic && root.dataset.nativeSidebarGlass === 'windows') {
          root.dataset.nativeSidebarMaterial = 'acrylic'
        }
      })
    }

    return () => {
      activeGlassSurfaces = Math.max(0, activeGlassSurfaces - 1)
      if (activeGlassSurfaces === 0) {
        delete root.dataset.nativeSidebarGlass
        delete root.dataset.nativeSidebarMaterial
      }
    }
  }, [active, os])
}
