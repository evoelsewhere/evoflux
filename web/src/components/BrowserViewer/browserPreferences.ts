import { STORAGE_KEYS } from '@/lib/storage-keys'

export interface BrowserPreferences {
  defaultZoom: number
  developerTools: boolean
}

const DEFAULT_BROWSER_PREFERENCES: BrowserPreferences = {
  defaultZoom: 100,
  developerTools: false,
}

const BROWSER_PREFERENCES_VERSION = 4

export function loadBrowserPreferences(): BrowserPreferences {
  try {
    const value = JSON.parse(
      localStorage.getItem(STORAGE_KEYS.browser.preferences) ?? '{}',
    ) as Partial<BrowserPreferences> & { version?: number }
    return {
      defaultZoom:
        typeof value.defaultZoom === 'number'
          ? Math.max(50, Math.min(200, value.defaultZoom))
          : DEFAULT_BROWSER_PREFERENCES.defaultZoom,
      developerTools: value.developerTools === true,
    }
  } catch {
    return DEFAULT_BROWSER_PREFERENCES
  }
}

export function saveBrowserPreferences(value: BrowserPreferences): void {
  try {
    localStorage.setItem(
      STORAGE_KEYS.browser.preferences,
      JSON.stringify({ version: BROWSER_PREFERENCES_VERSION, ...value }),
    )
  } catch {
    // Storage can be unavailable in hardened WebViews.
  }
}
