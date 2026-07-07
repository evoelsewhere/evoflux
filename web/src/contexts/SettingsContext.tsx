/**
 * SettingsContext — provides navigation primitives for settings sub-pages
 * so they don't depend on TanStack Router (settings is a store-driven modal).
 */
import { createContext, useContext, useMemo } from 'react'
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

/** Navigate within settings modal. Accepts full /settings/... paths or relative paths. */
// eslint-disable-next-line react-refresh/only-export-components
export function useSettingsNavigate() {
  const navigateSettings = useUIStore((s) => s.navigateSettings)
  return useMemo(
    () => (to: string, opts?: { params?: Record<string, string>; search?: Record<string, string> }) => {
      // Convert full path to relative: "/settings/agents/$name" + params → "agents/lead"
      let resolved = to.replace(/^\/settings\/?/, '')
      if (opts?.params) {
        for (const [key, value] of Object.entries(opts.params)) {
          resolved = resolved.replace(`$${key}`, value)
        }
      }
      navigateSettings(resolved, opts?.search)
    },
    [navigateSettings],
  )
}
