/**
 * Motion constants — typed counterparts to the CSS `--motion-*` / `--ease-*`
 * tokens defined in `web/src/index.css`.
 *
 * Use these when you need values inside TypeScript (framer-motion props,
 * inline styles computed at render time, animation delays). For static CSS
 * or Tailwind arbitrary values, prefer `var(--motion-*)` directly.
 *
 * The lower half of this file turns the Appearance → UI animations choice
 * into presets. Three layers consume the same intensity so the setting has
 * one meaning everywhere:
 *   1. CSS  — `--motion-user-scale` scales every `--motion-*` token, which
 *             Tailwind's default transition duration also resolves to.
 *   2. JS   — `AppMotionConfig` feeds the preset to framer-motion's
 *             `MotionConfig`, so components without an explicit transition
 *             inherit the user's choice.
 *   3. Opt-in — components needing physical motion read `spring`/`distance`
 *             through `useMotionPreset()`.
 *
 * Keep in sync with:
 * - `web/src/index.css` token block
 * - `web/public/appearance-init.js` pre-paint script
 * - `documents/styling-specs/motion.md` (semantic meaning of each value)
 */
import { useSyncExternalStore } from 'react'
import type { Transition } from 'framer-motion'

import {
  DEFAULT_APPEARANCE,
  MOTION_INTENSITIES,
  MOTION_SCALES,
  type MotionIntensity,
} from '@/lib/appearance'

/** Durations in milliseconds. */
export const DURATIONS = {
  instant: 80,
  fast: 150,
  base: 240,
  slow: 400,
  glacial: 800,
} as const
export type DurationName = keyof typeof DURATIONS

/** Durations in seconds — framer-motion takes seconds. */
export const DURATIONS_S = {
  instant: 0.08,
  fast: 0.15,
  base: 0.24,
  slow: 0.4,
  glacial: 0.8,
} as const

/** Cubic-bezier easings, framer-motion compatible `number[]` form. */
export const EASINGS = {
  out: [0.16, 1, 0.3, 1],
  inOut: [0.4, 0, 0.2, 1],
  springSoft: [0.34, 1.2, 0.64, 1],
  springSnappy: [0.22, 1.4, 0.36, 1],
  linear: [0, 0, 1, 1],
} as const satisfies Record<string, [number, number, number, number]>
export type EasingName = keyof typeof EASINGS

/**
 * Spring presets matching the Fluid Functionalism vocabulary.
 * Use these names verbatim in UI copy when letting users pick a preference.
 */
export const SPRINGS = {
  fast: { type: 'spring', stiffness: 380, damping: 28 },
  moderate: { type: 'spring', stiffness: 220, damping: 26 },
  slow: { type: 'spring', stiffness: 140, damping: 24 },
  comfortable: { type: 'spring', stiffness: 180, damping: 30 },
} as const
export type SpringName = keyof typeof SPRINGS

/** Keep JS-driven motion aligned with the global reduced-motion CSS gate. */
export function reducedMotionTransition<T>(reducedMotion: boolean, transition: T): T | { duration: number } {
  return reducedMotion ? { duration: 0.01 } : transition
}

/** Default spring — `moderate` unless the user overrides it. */
export const DEFAULT_SPRING = SPRINGS.moderate

/* ─────────────────────────────────────────────────────────────
 * Appearance → UI animations
 * ───────────────────────────────────────────────────────────── */

export interface MotionPreset {
  intensity: MotionIntensity
  /** Multiplier applied to duration tokens. 0 means "cut the animation". */
  scale: number
  /** Default transition handed to framer-motion's `MotionConfig`. */
  transition: Transition
  /** Physical spring for draggable/elastic surfaces (slider thumbs, panels). */
  spring: Transition
  /** Multiplier on enter-animation travel distance, in px terms. */
  distance: number
  /** Delay between sequential children, in seconds. */
  stagger: number
  /** Whether purely decorative loops (particles, ambient glow) may run. */
  ambient: boolean
}

const PRESETS: Record<MotionIntensity, MotionPreset> = {
  reduced: {
    intensity: 'reduced',
    scale: MOTION_SCALES.reduced,
    transition: { duration: 0 },
    spring: { duration: 0 },
    distance: 0,
    stagger: 0,
    ambient: false,
  },
  subtle: {
    intensity: 'subtle',
    scale: MOTION_SCALES.subtle,
    transition: { duration: 0.16, ease: EASINGS.out },
    spring: { type: 'spring', stiffness: 420, damping: 44, mass: 0.7 },
    distance: 0.5,
    stagger: 0.015,
    ambient: false,
  },
  standard: {
    intensity: 'standard',
    scale: MOTION_SCALES.standard,
    transition: { duration: DURATIONS_S.base, ease: EASINGS.out },
    spring: { type: 'spring', stiffness: 300, damping: 32, mass: 0.85 },
    distance: 1,
    stagger: 0.03,
    ambient: true,
  },
  expressive: {
    intensity: 'expressive',
    scale: MOTION_SCALES.expressive,
    transition: { duration: 0.32, ease: EASINGS.out },
    spring: { type: 'spring', stiffness: 240, damping: 22, mass: 0.9 },
    distance: 1.35,
    stagger: 0.045,
    ambient: true,
  },
  cinematic: {
    intensity: 'cinematic',
    scale: MOTION_SCALES.cinematic,
    transition: { duration: 0.44, ease: EASINGS.out },
    spring: { type: 'spring', stiffness: 170, damping: 18, mass: 1 },
    distance: 1.7,
    stagger: 0.06,
    ambient: true,
  },
}

export function motionPreset(intensity: MotionIntensity): MotionPreset {
  return PRESETS[intensity] ?? PRESETS[DEFAULT_APPEARANCE.motionIntensity]
}

function subscribeIntensity(onStoreChange: () => void): () => void {
  const observer = new MutationObserver(onStoreChange)
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-motion'] })
  const media = window.matchMedia('(prefers-reduced-motion: reduce)')
  media.addEventListener('change', onStoreChange)
  return () => {
    observer.disconnect()
    media.removeEventListener('change', onStoreChange)
  }
}

function readIntensity(): MotionIntensity {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return 'reduced'
  const value = document.documentElement.dataset.motion
  return MOTION_INTENSITIES.includes(value as MotionIntensity)
    ? (value as MotionIntensity)
    : DEFAULT_APPEARANCE.motionIntensity
}

/** Live motion preset. Re-renders when the user or the OS changes the preference. */
export function useMotionPreset(): MotionPreset {
  const intensity = useSyncExternalStore(
    subscribeIntensity,
    readIntensity,
    () => DEFAULT_APPEARANCE.motionIntensity,
  )
  return motionPreset(intensity)
}

/** Fade-and-rise variant whose travel distance follows the intensity. */
export function fadeRise(preset: MotionPreset, basePx = 8) {
  const offset = basePx * preset.distance
  return {
    initial: { opacity: 0, y: offset },
    animate: { opacity: 1, y: 0 },
    exit: { opacity: 0, y: offset * 0.5 },
    transition: preset.transition,
  }
}
