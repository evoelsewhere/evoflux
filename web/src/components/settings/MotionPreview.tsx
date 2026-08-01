/**
 * Plays the three motions the app uses most (panel slide, list rise, control
 * spring) at the currently selected intensity, so the setting can be judged
 * before leaving the page. Replays whenever the intensity changes.
 */
import { useState } from 'react'
import { motion } from 'framer-motion'
import { RotateCcw } from 'lucide-react'

import type { MotionIntensity } from '@/lib/appearance'
import { motionPreset, panelTransition, useMotionPreset } from '@/lib/motion'

export function MotionPreview({ intensity }: { intensity?: MotionIntensity }) {
  const livePreset = useMotionPreset()
  // Prefer the Appearance selection so the preview tracks the slider even when
  // the OS reduced-motion preference is gating live app motion.
  const preset = intensity ? motionPreset(intensity) : livePreset
  const [replay, setReplay] = useState(0)

  // The intensity is part of the key, so picking a new level remounts the
  // samples and plays them at once. Replay bumps the counter for a re-run.
  const key = `${preset.intensity}-${replay}`

  return (
    <div className="rounded-lg border border-(--color-border) bg-(--bg-page) p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-(--color-text-muted)">Preview</span>
        <button
          type="button"
          onClick={() => setReplay((value) => value + 1)}
          className="flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)"
        >
          <RotateCcw size={12} aria-hidden="true" />
          Replay
        </button>
      </div>

      <div className="mt-2.5 grid grid-cols-3 gap-2" aria-hidden="true">
        <div className="relative h-14 overflow-hidden rounded-md bg-(--bg-key)">
          <motion.div
            key={`panel-${key}`}
            initial={{ x: '100%' }}
            animate={{ x: '35%' }}
            transition={panelTransition(preset)}
            className="absolute inset-y-1 right-0 w-2/3 rounded-l-md bg-(--color-surface) ring-1 ring-(--color-border)"
          />
          <span className="absolute bottom-1 left-1.5 font-mono text-[9px] text-(--color-text-subtle)">panel</span>
        </div>

        <div className="relative flex h-14 flex-col justify-center gap-1 overflow-hidden rounded-md bg-(--bg-key) px-2">
          {[0, 1, 2].map((row) => (
            <motion.span
              key={`row-${row}-${key}`}
              initial={{ opacity: 0, y: 8 * preset.distance }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ ...preset.transition, delay: row * preset.stagger }}
              className="h-1.5 rounded-full bg-(--color-text-subtle)/50"
              style={{ width: `${88 - row * 18}%` }}
            />
          ))}
          <span className="absolute bottom-1 right-1.5 font-mono text-[9px] text-(--color-text-subtle)">list</span>
        </div>

        <div className="relative flex h-14 items-center justify-center overflow-hidden rounded-md bg-(--bg-key)">
          <motion.span
            key={`spring-${key}`}
            initial={{ scale: 0.6, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={preset.spring}
            className="size-6 rounded-full"
            style={{ backgroundColor: 'var(--color-accent)' }}
          />
          <span className="absolute bottom-1 left-1.5 font-mono text-[9px] text-(--color-text-subtle)">control</span>
        </div>
      </div>
    </div>
  )
}
