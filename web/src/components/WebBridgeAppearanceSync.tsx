import { useEffect } from 'react'

import { updateWebBridgeAppearance } from '@/api/client'
import { useAppearance } from '@/hooks/useAppearance'
import { useThemePreference } from '@/hooks/useThemePreference'

/**
 * Bridge device-local Desktop appearance into the separately sandboxed
 * Chromium extension. The snapshot contains presentation preferences only.
 */
export function WebBridgeAppearanceSync() {
  const { settings } = useAppearance()
  const { preference, resolved } = useThemePreference()

  useEffect(() => {
    const publish = () => {
      void updateWebBridgeAppearance({
        schema_version: 1,
        theme_preference: preference,
        resolved_theme: resolved,
        accent: settings.accent,
        font_family: settings.fontFamily,
        font_scale: settings.fontScale,
        motion_intensity: settings.motionIntensity,
      }).catch(() => {
        // Best effort: the app can render while the bundled sidecar is restarting.
      })
    }
    const publishWhenVisible = () => {
      if (document.visibilityState === 'visible') publish()
    }

    publish()
    const heartbeat = window.setInterval(publish, 15_000)
    window.addEventListener('focus', publish)
    document.addEventListener('visibilitychange', publishWhenVisible)
    return () => {
      window.clearInterval(heartbeat)
      window.removeEventListener('focus', publish)
      document.removeEventListener('visibilitychange', publishWhenVisible)
    }
  }, [
    preference,
    resolved,
    settings.accent,
    settings.fontFamily,
    settings.fontScale,
    settings.motionIntensity,
  ])

  return null
}
