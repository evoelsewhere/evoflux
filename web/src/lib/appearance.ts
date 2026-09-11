/**
 * Appearance — accent color, font family, UI scale, and motion intensity,
 * with localStorage persistence. Mirrors the split used by `lib/theme.ts`:
 * plain functions here, a reactive hook in `hooks/useAppearance.ts`.
 *
 * Settings apply as DOM overrides on `document.documentElement`. Pre-paint:
 * `web/public/appearance-init.js` — keep storage keys/logic in sync.
 */

import { STORAGE_KEYS } from '@/lib/storage-keys'

export type AccentColor =
  | 'default'
  | 'clay' | 'red' | 'orange' | 'amber' | 'lime' | 'green' | 'teal'
  | 'cyan' | 'blue' | 'indigo' | 'purple' | 'pink' | 'rose' | 'slate'
  | 'custom'
export type FontFamily = 'inter' | 'system' | 'mono' | 'geist' | 'anthropic-sans'
/** Legacy stored value migrated to anthropic-sans. */
type LegacyFontFamily = 'source-sans'
export type FontScale = 0.9 | 0.95 | 1 | 1.05 | 1.1 | 1.15 | 1.2
export type MotionIntensity = 'reduced' | 'subtle' | 'standard' | 'expressive' | 'cinematic'

export interface AppearanceSettings {
  accent: AccentColor
  /** Hex used when `accent` is 'custom'. Ignored otherwise. */
  accentCustom: string
  fontFamily: FontFamily
  fontScale: FontScale
  motionIntensity: MotionIntensity
}

export const APPEARANCE_STORAGE_KEY = STORAGE_KEYS.appearance

export const ACCENT_COLORS: readonly AccentColor[] = [
  'default',
  'clay', 'red', 'orange', 'amber', 'lime', 'green', 'teal',
  'cyan', 'blue', 'indigo', 'purple', 'pink', 'rose', 'slate',
  'custom',
]

/** The default accent, as a hex — the seed for a custom colour. */
export const DEFAULT_ACCENT_HEX = '#D97757'

const HEX_PATTERN = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i

export function normalizeAccentHex(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  const candidate = trimmed.startsWith('#') ? trimmed : `#${trimmed}`
  if (!HEX_PATTERN.test(candidate)) return null
  if (candidate.length === 4) {
    const [, r, g, b] = candidate
    return `#${r}${r}${g}${g}${b}${b}`.toLowerCase()
  }
  return candidate.toLowerCase()
}

/** WCAG relative luminance of an already-normalized `#rrggbb`. */
export function accentLuminance(hex: string): number {
  const channel = (pair: string) => {
    const value = parseInt(pair, 16) / 255
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  }
  const r = channel(hex.slice(1, 3))
  const g = channel(hex.slice(3, 5))
  const b = channel(hex.slice(5, 7))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contrastRatio(hex: string, againstLuminance: number): number {
  const lum = accentLuminance(hex)
  const [light, dark] = lum > againstLuminance ? [lum, againstLuminance] : [againstLuminance, lum]
  return (light + 0.05) / (dark + 0.05)
}

/**
 * Label colour for text sitting on `hex`, and how legible that pairing is.
 *
 * A preset is tuned per theme, so it can rely on the theme's own
 * `--color-text-on-accent`. A colour someone typed cannot: pick whichever of
 * near-black or white reads better on it, and report the ratio so the UI can
 * say when the choice is too faint to use.
 */
export function accentContrast(hex: string): { onAccent: string; ratio: number } {
  const onDark = contrastRatio(hex, accentLuminance('#211a16'))
  const onWhite = contrastRatio(hex, accentLuminance('#ffffff'))
  return onDark >= onWhite
    ? { onAccent: '#211A16', ratio: onDark }
    : { onAccent: '#FFFFFF', ratio: onWhite }
}
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
  accentCustom: DEFAULT_ACCENT_HEX,
  fontFamily: 'system',
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
      accent: ACCENT_COLORS.includes(parsed?.accent as AccentColor)
        ? (parsed!.accent as AccentColor)
        : DEFAULT_APPEARANCE.accent,
      accentCustom: normalizeAccentHex(parsed?.accentCustom) ?? DEFAULT_ACCENT_HEX,
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
    root.style.removeProperty('--color-text-on-accent')
  } else if (settings.accent === 'custom') {
    // A typed colour cannot lean on the theme's label colour, which is
    // picked for the theme's own accent. Derive one that actually reads.
    const hex = normalizeAccentHex(settings.accentCustom) ?? DEFAULT_ACCENT_HEX
    root.style.setProperty('--focus-ring', hex)
    root.style.setProperty('--color-accent', hex)
    root.style.setProperty('--color-text-on-accent', accentContrast(hex).onAccent)
  } else {
    const ref = `var(--ui-accent-${settings.accent})`
    root.style.setProperty('--focus-ring', ref)
    root.style.setProperty('--color-accent', ref)
    root.style.removeProperty('--color-text-on-accent')
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
