import { useQuery } from '@tanstack/react-query'
import { invoke } from '@tauri-apps/api/core'

import { getPlatform } from '@/hooks/use-platform'

import { computerAppSupported } from './computerAppBridge'

/** One program the user can allow or block, as the desktop reports it. */
export interface InstalledApp {
  /** Executable name, lower-case — what the policy matches on. */
  exe: string
  name: string
  running: boolean
  /** PNG data URL, when the shell had an icon for it. */
  icon: string | null
}

/**
 * Programs on this computer: every app with a window right now, and the
 * Start menu's programs. Desktop-only; elsewhere the list is empty and the
 * picker falls back to typed names.
 */
export function useInstalledApps() {
  const supported = computerAppSupported()
  return useQuery({
    queryKey: ['computer-app', 'installed-apps'],
    queryFn: async () => {
      const result = await invoke<{ apps: InstalledApp[] }>('app_computer_list_apps')
      return result.apps
    },
    enabled: supported,
    staleTime: 60_000,
  })
}

/**
 * "Notepad", "notepad.EXE" and "C:\\…\\notepad.exe" all name notepad.exe on
 * Windows. macOS executables have no suffix, so there a name is only
 * lower-cased: "TextEdit" and "/…/MacOS/TextEdit" name textedit.
 */
export function normalizeExe(value: string, windows = getPlatform().os === 'windows'): string {
  const name = value.trim().toLowerCase().split(/[\\/]/).pop() ?? ''
  return windows && name && !name.endsWith('.exe') ? `${name}.exe` : name
}
