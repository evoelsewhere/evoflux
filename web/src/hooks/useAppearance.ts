/** Reactive access to persisted appearance settings across hook instances and tabs. */
import { useEffect, useRef, useState } from 'react'
import {
  type AppearanceSettings,
  APPEARANCE_CHANGE_EVENT,
  APPEARANCE_STORAGE_KEY,
  readStoredAppearance,
  setStoredAppearance,
} from '@/lib/appearance'

export function useAppearance(): {
  settings: AppearanceSettings
  update: (patch: Partial<AppearanceSettings>) => void
} {
  const [settings, setSettings] = useState<AppearanceSettings>(() => readStoredAppearance())
  const settingsRef = useRef(settings)

  useEffect(() => {
    const applySyncedSettings = (next: AppearanceSettings) => {
      settingsRef.current = next
      setSettings(next)
    }
    const onStorage = (event: StorageEvent) => {
      if (event.key === APPEARANCE_STORAGE_KEY) applySyncedSettings(readStoredAppearance())
    }
    const onAppearanceChange = (event: Event) => {
      applySyncedSettings((event as CustomEvent<AppearanceSettings>).detail)
    }

    window.addEventListener('storage', onStorage)
    window.addEventListener(APPEARANCE_CHANGE_EVENT, onAppearanceChange)
    return () => {
      window.removeEventListener('storage', onStorage)
      window.removeEventListener(APPEARANCE_CHANGE_EVENT, onAppearanceChange)
    }
  }, [])

  const update = (patch: Partial<AppearanceSettings>) => {
    const next = { ...settingsRef.current, ...patch }
    settingsRef.current = next
    setSettings(next)
    setStoredAppearance(next)
  }

  return { settings, update }
}
