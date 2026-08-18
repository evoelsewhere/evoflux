import { STORAGE_KEYS } from '@/lib/storage-keys'

export interface BrowserPreferences {
  /** Whether the built-in workspace browser is available. */
  enabled: boolean
  defaultZoom: number
  developerTools: boolean
  profileMode: 'shared' | 'session' | 'incognito'
}

const DEFAULT_BROWSER_PREFERENCES: BrowserPreferences = {
  enabled: true,
  defaultZoom: 100,
  developerTools: false,
  profileMode: 'shared',
}

const BROWSER_PREFERENCES_VERSION = 5
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
