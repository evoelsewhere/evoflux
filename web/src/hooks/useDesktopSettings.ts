import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { invoke } from '@tauri-apps/api/core'

import { getPlatform } from '@/hooks/use-platform'

/**
 * Settings → Desktop, as the Tauri shell reports it
 * (``desktop/src-tauri/src/desktop_settings.rs``).
 */
export interface DesktopSettings {
  /** The OS login entry exists and is not switched off by the user. */
  run_on_startup: boolean
  /** Tray / menu bar icon; on Windows and Linux it also keeps EvoFlux running after the last window closes. */
  tray_icon: boolean
  /** Stop the system idling into sleep while EvoFlux runs. */
  keep_awake: boolean
}

export type DesktopSettingsPatch = Partial<DesktopSettings>

const DESKTOP_SETTINGS_KEY = ['desktop', 'settings'] as const

/** Only the packaged desktop app on a desktop OS has these settings. */
export function desktopSettingsSupported(): boolean {
  const platform = getPlatform()
  return platform.isTauri && (platform.os === 'windows' || platform.os === 'macos' || platform.os === 'linux')
}

export function useDesktopSettings() {
  return useQuery({
    queryKey: DESKTOP_SETTINGS_KEY,
    queryFn: () => invoke<DesktopSettings>('app_desktop_settings'),
    enabled: desktopSettingsSupported(),
    // Run on startup can be switched off from Task Manager or System
    // Settings while EvoFlux is open.
    refetchOnWindowFocus: true,
  })
}

export function useUpdateDesktopSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (patch: DesktopSettingsPatch) =>
      invoke<DesktopSettings>('app_update_desktop_settings', { patch }),
    onMutate: async (patch) => {
      await queryClient.cancelQueries({ queryKey: DESKTOP_SETTINGS_KEY })
      const previous = queryClient.getQueryData<DesktopSettings>(DESKTOP_SETTINGS_KEY)
      if (previous) queryClient.setQueryData(DESKTOP_SETTINGS_KEY, { ...previous, ...patch })
      return { previous }
    },
    onError: (_error, _patch, context) => {
      if (context?.previous) queryClient.setQueryData(DESKTOP_SETTINGS_KEY, context.previous)
    },
    onSuccess: (settings) => queryClient.setQueryData(DESKTOP_SETTINGS_KEY, settings),
  })
}
