import { STORAGE_KEYS } from '@/lib/storage-keys'

export interface BrowserPreferences {
  /** Whether the built-in workspace browser is available. */
  enabled: boolean
  defaultZoom: number
  /**
   * Lay pages out at {@link FIT_DESKTOP_WIDTH} and scale them down while the
   * panel is narrower, so a docked browser shows a site's desktop layout
   * rather than the tablet one its own width would trigger.
   */
  fitDesktopWidth: boolean
  developerTools: boolean
  profileMode: 'shared' | 'session' | 'incognito'
}

/** The layout width a fitted page is rendered at. */
export const FIT_DESKTOP_WIDTH = 1280

const DEFAULT_BROWSER_PREFERENCES: BrowserPreferences = {
  enabled: true,
  defaultZoom: 100,
  fitDesktopWidth: true,
  developerTools: false,
  profileMode: 'shared',
}

const BROWSER_PREFERENCES_VERSION = 6
const BROWSER_PREFERENCES_CHANGED = 'oa-browser-preferences-changed'

export function loadBrowserPreferences(): BrowserPreferences {
  try {
    const value = JSON.parse(
      localStorage.getItem(STORAGE_KEYS.browser.preferences) ?? '{}',
    ) as Partial<BrowserPreferences> & { version?: number }
    return {
      enabled: value.enabled !== false,
      defaultZoom:
        typeof value.defaultZoom === 'number'
          ? Math.max(50, Math.min(200, value.defaultZoom))
          : DEFAULT_BROWSER_PREFERENCES.defaultZoom,
      fitDesktopWidth: value.fitDesktopWidth !== false,
      developerTools: value.developerTools === true,
      profileMode: value.profileMode === 'session' || value.profileMode === 'incognito'
        ? value.profileMode
        : 'shared',
    }
  } catch {
    return { ...DEFAULT_BROWSER_PREFERENCES }
  }
}

export function saveBrowserPreferences(value: BrowserPreferences): void {
  try {
    localStorage.setItem(
      STORAGE_KEYS.browser.preferences,
      JSON.stringify({ version: BROWSER_PREFERENCES_VERSION, ...value }),
    )
    window.dispatchEvent(new CustomEvent(BROWSER_PREFERENCES_CHANGED))
  } catch {
    // Storage can be unavailable in hardened WebViews.
  }
}

/** Subscribe to preference writes from other settings surfaces. */
export function subscribeBrowserPreferences(
  listener: (value: BrowserPreferences) => void,
): () => void {
  const handler = () => listener(loadBrowserPreferences())
  window.addEventListener(BROWSER_PREFERENCES_CHANGED, handler)
  window.addEventListener('storage', handler)
  return () => {
    window.removeEventListener(BROWSER_PREFERENCES_CHANGED, handler)
    window.removeEventListener('storage', handler)
  }
}

export interface BrowserRecentSite {
  origin: string
  host: string
  /** Last full address seen there, so a deep link comes back deep. */
  url: string
  visitedAt: number
}

const MAX_RECENT_SITES = 8

/**
 * A short memory of where this browser has been.
 *
 * The panel has no history of its own, so an empty new tab was a dead end:
 * the only way back to a page was to type it again from memory.
 */
export function loadRecentBrowserSites(): BrowserRecentSite[] {
  try {
    const raw = JSON.parse(
      localStorage.getItem(STORAGE_KEYS.browser.recentSites) ?? '[]',
    ) as unknown
    if (!Array.isArray(raw)) return []
    return raw.flatMap((entry) => {
      if (!entry || typeof entry !== 'object') return []
      const { origin, host, url, visitedAt } = entry as Record<string, unknown>
      if (typeof origin !== 'string' || typeof host !== 'string' || typeof url !== 'string') {
        return []
      }
      return [{
        origin,
        host,
        url,
        visitedAt: typeof visitedAt === 'number' ? visitedAt : 0,
      }]
    }).slice(0, MAX_RECENT_SITES)
  } catch {
    return []
  }
}

export function recordRecentBrowserSite(url: string): BrowserRecentSite[] | null {
  const origin = browserZoomOrigin(url)
  if (!origin) return null
  try {
    const host = new URL(url).host
    const existing = loadRecentBrowserSites().filter((site) => site.origin !== origin)
    const next = [{ origin, host, url, visitedAt: Date.now() }, ...existing]
      .slice(0, MAX_RECENT_SITES)
    localStorage.setItem(STORAGE_KEYS.browser.recentSites, JSON.stringify(next))
    return next
  } catch {
    return null
  }
}

export interface BrowserConnectionInfo {
  /** Scheme + host, or null for a page that is not on the web. */
  origin: string | null
  scheme: string
  host: string
  encrypted: boolean
  /** Plain words for the state of the connection, for the site panel. */
  summary: string
}

/**
 * What the padlock in the address bar is actually claiming.
 *
 * It used to be `url.startsWith('https://')`, which called a local page
 * insecure and had nothing to say about anything else.
 */
export function browserConnectionInfo(url: string): BrowserConnectionInfo {
  let parsed: URL | null = null
  try {
    parsed = new URL(url)
  } catch {
    parsed = null
  }
  if (!parsed) {
    return { origin: null, scheme: '', host: '', encrypted: false, summary: 'No page loaded' }
  }
  const scheme = parsed.protocol.replace(':', '')
  const host = parsed.host
  if (scheme === 'https') {
    return {
      origin: `${parsed.protocol}//${host}`,
      scheme,
      host,
      encrypted: true,
      summary: 'Encrypted connection',
    }
  }
  if (scheme === 'http') {
    // Loopback is delivered by a process on this machine; calling that
    // "not secure" teaches people to ignore the warning that matters.
    const local = /^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/i.test(host)
    return {
      origin: `${parsed.protocol}//${host}`,
      scheme,
      host,
      encrypted: false,
      summary: local ? 'Local server on this machine' : 'Not encrypted',
    }
  }
  if (scheme === 'file') {
    return { origin: null, scheme, host, encrypted: false, summary: 'File on this machine' }
  }
  return { origin: null, scheme, host, encrypted: false, summary: `${scheme} page` }
}

/**
 * Zoom is remembered per site, not per app.
 *
 * A default zoom applied to everything is the wrong unit: one site needs
 * 125% because its type is small, and applying that to every other site — and
 * to the next session — is not what the person adjusting it asked for.
 */
const MAX_REMEMBERED_ZOOM_ORIGINS = 100

export function browserZoomOrigin(url: string): string | null {
  try {
    const { protocol, host } = new URL(url)
    if (!/^https?:$/.test(protocol) || !host) return null
    return `${protocol}//${host}`
  } catch {
    return null
  }
}

export function loadBrowserZoomForOrigin(origin: string | null): number | null {
  if (!origin) return null
  try {
    const raw = JSON.parse(
      localStorage.getItem(STORAGE_KEYS.browser.zoomByOrigin) ?? '{}',
    ) as Record<string, unknown>
    const value = raw[origin]
    return typeof value === 'number' && value >= 25 && value <= 500 ? value : null
  } catch {
    return null
  }
}

export function saveBrowserZoomForOrigin(origin: string | null, zoom: number | null): void {
  if (!origin) return
  try {
    const key = STORAGE_KEYS.browser.zoomByOrigin
    const raw = JSON.parse(localStorage.getItem(key) ?? '{}') as Record<string, number>
    if (zoom === null) delete raw[origin]
    else raw[origin] = zoom
    const entries = Object.entries(raw).slice(-MAX_REMEMBERED_ZOOM_ORIGINS)
    localStorage.setItem(key, JSON.stringify(Object.fromEntries(entries)))
  } catch {
    // Storage can be unavailable in hardened WebViews.
  }
}

export function isBuiltInBrowserEnabled(): boolean {
  return loadBrowserPreferences().enabled
}

export function areWebBridgeDefaultsEnabled(): boolean {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(STORAGE_KEYS.browser.webBridgeDefaultEnabled) === 'true'
}

export function setWebBridgeDefaultsEnabled(enabled: boolean): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(STORAGE_KEYS.browser.webBridgeDefaultEnabled, String(enabled))
  window.dispatchEvent(new CustomEvent(BROWSER_PREFERENCES_CHANGED))
}
