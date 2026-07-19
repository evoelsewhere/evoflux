/**
 * Appearance — accent color, font family, and UI scale, with localStorage
 * persistence. Mirrors the split used by `lib/theme.ts`: plain functions
 * here, a reactive hook in `hooks/useAppearance.ts`.
 *
 * All three settings apply as inline CSS custom-property overrides on
 * `document.documentElement`, which win over the `:root.dark`/`:root.light`
 * rules in `index.css` without touching them — "default" removes the
 * override and falls back to the theme's own value.
 *
 * Pre-paint: `web/public/appearance-init.js` applies the same overrides
 * before first paint to avoid a flash of default appearance. Keep the
 * storage key and logic here in sync with that script.
 */

import { STORAGE_KEYS } from '@/lib/storage-keys'

export type AccentColor = 'default' | 'blue' | 'green' | 'orange' | 'pink' | 'purple' | 'red'
export type FontFamily = 'inter' | 'system' | 'mono'
export type FontScale = 0.9 | 1 | 1.1 | 1.2

export interface AppearanceSettings {
  accent: AccentColor
  fontFamily: FontFamily
  fontScale: FontScale
}

export const APPEARANCE_STORAGE_KEY = STORAGE_KEYS.appearance

export const ACCENT_COLORS: readonly AccentColor[] = ['default', 'blue', 'green', 'orange', 'pink', 'purple', 'red']
export const FONT_FAMILIES: readonly FontFamily[] = ['inter', 'system', 'mono']
export const FONT_SCALES: readonly FontScale[] = [0.9, 1, 1.1, 1.2]

const BASE_FONT_SIZE_PX = 18

const FONT_STACKS: Record<FontFamily, string | null> = {
  inter: null,
  system: `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, system-ui, sans-serif`,
  mono: `'JetBrains Mono Variable', ui-monospace, 'SF Mono', 'Cascadia Code', 'Fira Code', 'Courier New', monospace`,
}

export const DEFAULT_APPEARANCE: AppearanceSettings = {
  accent: 'default',
  fontFamily: 'inter',
  fontScale: 1,
}

export function readStoredAppearance(): AppearanceSettings {
  try {
    const raw = localStorage.getItem(APPEARANCE_STORAGE_KEY)
    if (!raw) return DEFAULT_APPEARANCE
    const parsed = JSON.parse(raw) as Partial<AppearanceSettings> | null
    return {
      accent: ACCENT_COLORS.includes(parsed?.accent as AccentColor) ? (parsed!.accent as AccentColor) : DEFAULT_APPEARANCE.accent,
      fontFamily: FONT_FAMILIES.includes(parsed?.fontFamily as FontFamily) ? (parsed!.fontFamily as FontFamily) : DEFAULT_APPEARANCE.fontFamily,
      fontScale: FONT_SCALES.includes(parsed?.fontScale as FontScale) ? (parsed!.fontScale as FontScale) : DEFAULT_APPEARANCE.fontScale,
    }
  } catch {
    return DEFAULT_APPEARANCE
  }
}

export function applyAppearance(settings: AppearanceSettings): void {
  const root = document.documentElement

  if (settings.accent === 'default') {
    root.style.removeProperty('--focus-ring')
    root.style.removeProperty('--color-accent')
  } else {
    const ref = `var(--accent-${settings.accent})`
    root.style.setProperty('--focus-ring', ref)
    root.style.setProperty('--color-accent', ref)
  }

  const stack = FONT_STACKS[settings.fontFamily]
  if (stack) {
    root.style.setProperty('--font-sans', stack)
    root.style.setProperty('--font-heading', stack)
  } else {
    root.style.removeProperty('--font-sans')
    root.style.removeProperty('--font-heading')
  }

  if (settings.fontScale === 1) {
    root.style.removeProperty('font-size')
  } else {
    root.style.setProperty('font-size', `${BASE_FONT_SIZE_PX * settings.fontScale}px`)
  }
}

export function setStoredAppearance(settings: AppearanceSettings): void {
  try {
    localStorage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify(settings))
  } catch {
    // best-effort — still apply below
  }
  applyAppearance(settings)
}

/** Initialise appearance on load. Safe to call after the pre-paint script. */
export function initAppearance(): void {
  applyAppearance(readStoredAppearance())
}
