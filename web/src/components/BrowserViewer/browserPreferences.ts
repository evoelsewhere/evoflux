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
