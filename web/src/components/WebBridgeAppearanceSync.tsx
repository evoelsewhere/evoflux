import { useEffect, useRef } from 'react'

import { updateWebBridgeAppearance } from '@/api/client'
import { useAppearance } from '@/hooks/useAppearance'
import { useThemePreference } from '@/hooks/useThemePreference'

/**
 * Bridge device-local Desktop appearance into the separately sandboxed
 * Chromium extension. The snapshot contains presentation preferences only.
 *
 * Appearance changes when a person changes it, which is rarely — so this
 * publishes on change and otherwise stays quiet. It used to re-send the
 * identical payload on a 15-second heartbeat *and* on every focus and
 * visibility change, which on an idle window measured ~10 writes a minute,
 * none of them carrying new information.
 *
 * The heartbeat is kept only for the case that justified it: the bundled
 * sidecar restarting and losing the snapshot. It re-sends when the last
 * attempt failed, and skips when the far side already has this payload.
 */
export function WebBridgeAppearanceSync() {
  const { settings } = useAppearance()
  const { preference, resolved } = useThemePreference()

  // What the sidecar last acknowledged, so an unchanged snapshot is not
  // sent again. Held in a ref because it must not itself cause a render.
  const publishedRef = useRef<string | null>(null)

  const snapshot = JSON.stringify({
    schema_version: 1,
    theme_preference: preference,
    resolved_theme: resolved,
    accent: settings.accent,
    font_family: settings.fontFamily,
    font_scale: settings.fontScale,
    motion_intensity: settings.motionIntensity,
  })

  useEffect(() => {
    let cancelled = false

    const publish = (force = false) => {
      if (!force && publishedRef.current === snapshot) return
      void updateWebBridgeAppearance(JSON.parse(snapshot))
        .then(() => {
          if (!cancelled) publishedRef.current = snapshot
        })
        .catch(() => {
          // Best effort: the app can render while the bundled sidecar is
          // restarting. Clearing the mark is what lets the heartbeat retry.
          if (!cancelled) publishedRef.current = null
        })
    }

    publish()
    // Retry only — a successful publish leaves nothing for this to do.
    const heartbeat = window.setInterval(() => publish(), 30_000)
    const onFocus = () => publish()
    const onVisibility = () => {
      if (document.visibilityState === 'visible') publish()
    }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      cancelled = true
      window.clearInterval(heartbeat)
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [snapshot])

  return null
}
