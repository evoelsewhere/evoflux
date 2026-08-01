/**
 * SettingsContext — provides navigation primitives for settings sub-pages
 * so they don't depend on TanStack Router (the screen preserves the app URL).
 */
import { createContext, useCallback, useContext, useMemo } from 'react'
import { confirmDiscardSettingsDraft } from '@/lib/settings-dirty'
import { useUIStore } from '@/stores/useUIStore'

interface SettingsContextValue {
  /** Current relative settings path, e.g. "agents/lead" */
  path: string
  /** Params parsed from path, e.g. { name: "lead" } */
  params: Record<string, string>
  /** Search params (e.g. { mode: "coding" }) */
  search: Record<string, string>
}

const SettingsContext = createContext<SettingsContextValue>({
  path: '',
  params: {},
  search: {},
})

export function SettingsProvider({
  path,
  params,
  search,
  children,
}: SettingsContextValue & { children: React.ReactNode }) {
  const value = useMemo(() => ({ path, params, search }), [path, params, search])
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>
}

/** Get parsed params from the current settings path. */
// eslint-disable-next-line react-refresh/only-export-components
export function useSettingsParams(): Record<string, string> {
  return useContext(SettingsContext).params
}

/** Get search params passed when opening settings. */
// eslint-disable-next-line react-refresh/only-export-components
export function useSettingsSearch(): Record<string, string> {
  return useContext(SettingsContext).search
}

export type SettingsNavigateOptions = {
  params?: Record<string, string>
  search?: Record<string, string>
  /** Skip the unsaved-draft confirm (e.g. explicit "Leave without saving"). */
  force?: boolean
}

/** Navigate within the settings screen. Accepts full /settings/... paths or relative paths. */
// eslint-disable-next-line react-refresh/only-export-components
export function useSettingsNavigate() {
  const navigateSettings = useUIStore((s) => s.navigateSettings)
  return useCallback(
    (to: string, opts?: SettingsNavigateOptions) => {
      // Convert full path to relative: "/settings/agents/$name" + params → "agents/lead"
      let resolved = to.replace(/^\/settings\/?/, '')
      if (opts?.params) {
        for (const [key, value] of Object.entries(opts.params)) {
          resolved = resolved.replace(`$${key}`, value)
        }
      }
      if (!opts?.force && !confirmDiscardSettingsDraft()) return
      navigateSettings(resolved, opts?.search)
    },
    [navigateSettings],
  )
}

/** Close settings, confirming when an editor draft is dirty. */
// eslint-disable-next-line react-refresh/only-export-components
export function useSettingsClose() {
  const closeSettings = useUIStore((s) => s.closeSettings)
  return useCallback(
    (opts?: { force?: boolean }) => {
      if (!opts?.force && !confirmDiscardSettingsDraft()) return
      closeSettings()
    },
    [closeSettings],
  )
}
