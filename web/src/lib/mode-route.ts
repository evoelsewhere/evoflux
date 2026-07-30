import { STORAGE_KEYS } from '@/lib/storage-keys'

export type PersistedAppMode = 'forge' | 'coding' | 'aim'

const MODE_ROUTE_KEYS: Record<PersistedAppMode, string> = {
  forge: STORAGE_KEYS.modeRoutes.forge,
  coding: STORAGE_KEYS.modeRoutes.coding,
  aim: STORAGE_KEYS.modeRoutes.aim,
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
  if (pathname === '/aim' || pathname.startsWith('/aim/')) return 'aim'
  if (pathname === '/coding' || pathname.startsWith('/coding/')) return 'coding'
  if (pathname === '/telemetry' || pathname.startsWith('/telemetry/')) return null
  if (pathname === '/scheduler' || pathname.startsWith('/scheduler/')) return null
  return 'forge'
}

function isSafeLocalRoute(route: string): boolean {
  return route.startsWith('/') && !route.startsWith('//')
}

export function saveModeRoute(pathname: string, fullPath: string): void {
  const mode = appModeForPath(pathname)
  if (!mode || !isSafeLocalRoute(fullPath)) return
  try {
    localStorage.setItem(MODE_ROUTE_KEYS[mode], fullPath)
  } catch {
    // Ignore unavailable/full storage.
  }
}

export function loadModeRoute(mode: PersistedAppMode): string | null {
  try {
    const route = localStorage.getItem(MODE_ROUTE_KEYS[mode])
    if (!route || !isSafeLocalRoute(route)) return null
    return appModeForPath(pathnameOf(route)) === mode ? route : null
  } catch {
    return null
  }
}

/**
 * Restore the last route before TanStack Router captures its initial location.
 * This prevents the Forge layout from mounting and starting requests for one
 * frame before an effect redirects to the user's actual last mode.
 */
export function restoreLastRouteBeforeRouterMount(): void {
  if (typeof window === 'undefined') return
  if (window.location.pathname !== '/' || window.location.search !== '') return
  try {
    const savedRoute = localStorage.getItem(STORAGE_KEYS.lastRoute)
    if (!savedRoute || savedRoute === '/' || !isSafeLocalRoute(savedRoute)) return
    window.history.replaceState(window.history.state, '', savedRoute)
  } catch {
    // Keep the current route when storage/history is unavailable.
  }
}
