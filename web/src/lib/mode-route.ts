import { STORAGE_KEYS } from '@/lib/storage-keys'

export type PersistedAppMode = 'work' | 'coding'

const MODE_ROUTE_KEYS: Record<PersistedAppMode, string> = {
  work: STORAGE_KEYS.modeRoutes.work,
  coding: STORAGE_KEYS.modeRoutes.coding,
}

function pathnameOf(route: string): string {
  const queryIndex = route.indexOf('?')
  const hashIndex = route.indexOf('#')
  const end = Math.min(
    queryIndex === -1 ? route.length : queryIndex,
    hashIndex === -1 ? route.length : hashIndex,
  )
  return route.slice(0, end)
}

export function appModeForPath(pathname: string): PersistedAppMode | null {
  if (pathname === '/coding' || pathname.startsWith('/coding/')) return 'coding'
  // Retired AIM product mode — never treat as Work, or last-route restore
  // / ModeSwitch can poison Work navigation with a 404 `/aim` path.
  if (pathname === '/aim' || pathname.startsWith('/aim/')) return null
  if (pathname === '/telemetry' || pathname.startsWith('/telemetry/')) return null
  if (pathname === '/scheduler' || pathname.startsWith('/scheduler/')) return null
  return 'work'
}

function isSafeLocalRoute(route: string): boolean {
  return route.startsWith('/') && !route.startsWith('//')
}

export function saveModeRoute(pathname: string, fullPath: string): void {
  const mode = appModeForPath(pathname)
  if (!mode || !isSafeLocalRoute(fullPath)) return
  try {
    // Entering Coding mode is intentionally session-neutral. Keep Work
    // route restoration, but persist only the Coding landing page so mode
    // switches never reopen a previous workspace/project session.
    localStorage.setItem(MODE_ROUTE_KEYS[mode], mode === 'coding' ? '/coding' : fullPath)
  } catch {
    // Ignore unavailable/full storage.
  }
}

export function loadModeRoute(mode: PersistedAppMode): string | null {
  try {
    const route = localStorage.getItem(MODE_ROUTE_KEYS[mode])
      ?? (mode === 'work' ? localStorage.getItem(STORAGE_KEYS.legacyModeRoutes.work) : null)
    if (!route || !isSafeLocalRoute(route)) return null
    if (appModeForPath(pathnameOf(route)) !== mode) {
      // Drop retired/mismatched values (e.g. former `/aim` written under Work).
      localStorage.removeItem(MODE_ROUTE_KEYS[mode])
      return null
    }
    // Normalize dynamic routes saved by older releases to the session-neutral
    // Coding landing page.
    if (mode === 'coding') return '/coding'
    if (mode === 'work' && !localStorage.getItem(MODE_ROUTE_KEYS.work)) {
      localStorage.setItem(MODE_ROUTE_KEYS.work, route)
    }
    return route
  } catch {
    return null
  }
}

/**
 * Restore the last route before TanStack Router captures its initial location.
 * This prevents the Work layout from mounting and starting requests for one
 * frame before an effect redirects to the user's actual last mode.
 */
export function restoreLastRouteBeforeRouterMount(): void {
  if (typeof window === 'undefined') return
  if (window.location.pathname !== '/' || window.location.search !== '') return
  try {
    const savedRoute = localStorage.getItem(STORAGE_KEYS.lastRoute)
    if (!savedRoute || savedRoute === '/' || !isSafeLocalRoute(savedRoute)) return
    const mode = appModeForPath(pathnameOf(savedRoute))
    if (mode === 'coding') {
      window.history.replaceState(window.history.state, '', '/coding')
      return
    }
    if (mode === 'work') {
      window.history.replaceState(window.history.state, '', savedRoute)
      return
    }
    // Retired modes (e.g. former `/aim`) or standalone pages — stay on `/`
    // and clear the stale last-route so Work is not poisoned later.
    localStorage.removeItem(STORAGE_KEYS.lastRoute)
  } catch {
    // Keep the current route when storage/history is unavailable.
  }
}
