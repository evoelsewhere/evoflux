/**
 * useAppearance — reactive access to the stored appearance settings
 * (accent color, font family, UI scale).
 *
 * `update` uses React's functional `setState` form so several calls in the
 * same synchronous tick (e.g. a "reset to defaults" handler that patches
 * accent, font, and scale back to back) thread correctly against each
 * other instead of racing — each queued updater runs against the
 * *previous* queued updater's result, guaranteed by React regardless of
 * batching. Cross-tab sync only listens to the native `storage` event,
 * which never fires in the tab that made the change, so there's no
 * same-tab echo to guard against.
 */
import { useEffect, useState } from 'react'
import {
  type AppearanceSettings,
  APPEARANCE_STORAGE_KEY,
  readStoredAppearance,
  setStoredAppearance,
} from '@/lib/appearance'

export function useAppearance(): {
  settings: AppearanceSettings
  update: (patch: Partial<AppearanceSettings>) => void
} {
  const [settings, setSettings] = useState<AppearanceSettings>(() => readStoredAppearance())

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === APPEARANCE_STORAGE_KEY) setSettings(readStoredAppearance())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const update = (patch: Partial<AppearanceSettings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch }
      setStoredAppearance(next)
      return next
    })
  }

  return { settings, update }
}
