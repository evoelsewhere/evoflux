/**
 * Appearance — accent color, font family, UI scale, and motion intensity,
 * with localStorage persistence. Mirrors the split used by `lib/theme.ts`:
 * plain functions here, a reactive hook in `hooks/useAppearance.ts`.
 *
 * Settings apply as DOM overrides on `document.documentElement`. Pre-paint:
 * `web/public/appearance-init.js` — keep storage keys/logic in sync.
 */

import { STORAGE_KEYS } from '@/lib/storage-keys'

export type AccentColor = 'default' | 'blue' | 'green' | 'orange' | 'pink' | 'purple' | 'red'
export type FontFamily = 'inter' | 'system' | 'mono' | 'geist' | 'anthropic-sans'
/** Legacy stored value migrated to anthropic-sans. */
type LegacyFontFamily = 'source-sans'
export type FontScale = 0.9 | 0.95 | 1 | 1.05 | 1.1 | 1.15 | 1.2
export type MotionIntensity = 'reduced' | 'subtle' | 'standard' | 'expressive' | 'cinematic'

export interface AppearanceSettings {
  accent: AccentColor
  fontFamily: FontFamily
  fontScale: FontScale
  motionIntensity: MotionIntensity
}

export const APPEARANCE_STORAGE_KEY = STORAGE_KEYS.appearance

export const ACCENT_COLORS: readonly AccentColor[] = ['default', 'blue', 'green', 'orange', 'pink', 'purple', 'red']
export const FONT_FAMILIES: readonly FontFamily[] = ['inter', 'system', 'mono', 'geist', 'anthropic-sans']
export const FONT_SCALES: readonly FontScale[] = [0.9, 0.95, 1, 1.05, 1.1, 1.15, 1.2]
export const MOTION_INTENSITIES: readonly MotionIntensity[] = [
  'reduced',
  'subtle',
  'standard',
  'expressive',
  'cinematic',
]
export const APPEARANCE_CHANGE_EVENT = 'evoflux:appearance-change'

/**
 * Multiplier applied to every `--motion-*` duration token, and to the
 * framer-motion presets in `lib/motion.ts`. `0` collapses transitions to
 * nothing. Mirrored by `web/public/appearance-init.js` for pre-paint.
 */
export const MOTION_SCALES: Record<MotionIntensity, number> = {
  reduced: 0,
  subtle: 0.7,
  standard: 1,
  expressive: 1.25,
  cinematic: 1.55,
}

// Keep this aligned with the 16px rem baseline in index.css. The previous
// 18px multiplier made the first step above 100% jump from 16px to 18.9px.
const BASE_FONT_SIZE_PX = 16

export const DEFAULT_APPEARANCE: AppearanceSettings = {
  accent: 'default',
  fontFamily: 'inter',
  fontScale: 1,
  motionIntensity: 'standard',
}

function normalizeFontFamily(value: unknown): FontFamily {
  if (value === 'source-sans') return 'anthropic-sans'
  return FONT_FAMILIES.includes(value as FontFamily)
    ? (value as FontFamily)
    : DEFAULT_APPEARANCE.fontFamily
}

function nearestFontScale(value: unknown): FontScale {
  const numeric = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(numeric)) return DEFAULT_APPEARANCE.fontScale
  if (FONT_SCALES.includes(numeric as FontScale)) return numeric as FontScale
  let best: FontScale = DEFAULT_APPEARANCE.fontScale
  let bestDelta = Number.POSITIVE_INFINITY
  for (const scale of FONT_SCALES) {
    const delta = Math.abs(scale - numeric)
    if (delta < bestDelta) {
      best = scale
      bestDelta = delta
    }
  }
  return best
}

export function readStoredAppearance(): AppearanceSettings {
  try {
    const raw = localStorage.getItem(APPEARANCE_STORAGE_KEY)
    if (!raw) return DEFAULT_APPEARANCE
    const parsed = JSON.parse(raw) as Partial<AppearanceSettings & { fontFamily: FontFamily | LegacyFontFamily }> | null
    return {
      accent: ACCENT_COLORS.includes(parsed?.accent as AccentColor) ? (parsed!.accent as AccentColor) : DEFAULT_APPEARANCE.accent,
      fontFamily: normalizeFontFamily(parsed?.fontFamily),
      fontScale: nearestFontScale(parsed?.fontScale),
      motionIntensity: MOTION_INTENSITIES.includes(parsed?.motionIntensity as MotionIntensity)
        ? (parsed!.motionIntensity as MotionIntensity)
        : DEFAULT_APPEARANCE.motionIntensity,
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

  root.dataset.font = settings.fontFamily
  root.dataset.motion = settings.motionIntensity
  // Remove legacy inline overrides. Tailwind font utilities now resolve
  // through the runtime --app-font-* tokens selected by data-font.
  root.style.removeProperty('--font-sans')
  root.style.removeProperty('--font-heading')

  if (settings.fontScale === 1) {
    root.style.removeProperty('font-size')
  } else {
    root.style.setProperty('font-size', `${BASE_FONT_SIZE_PX * settings.fontScale}px`)
  }

  root.style.setProperty('--motion-user-scale', String(MOTION_SCALES[settings.motionIntensity]))
}

export function setStoredAppearance(settings: AppearanceSettings): void {
  try {
    localStorage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify(settings))
  } catch {
    // best-effort — still apply below
  }
  applyAppearance(settings)
  window.dispatchEvent(new CustomEvent<AppearanceSettings>(APPEARANCE_CHANGE_EVENT, { detail: settings }))
}

/** Initialise appearance on load. Safe to call after the pre-paint script. */
export function initAppearance(): void {
  applyAppearance(readStoredAppearance())
}
