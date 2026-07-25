/**
 * LoadingVerb — Whimsical gerund indicator.
 *
 * Rotates through playful single-word actions (Brewing, Ruminating,
 * Tinkering …) with letter-by-letter transitions that follow the
 * Appearance → UI animations intensity.
 */
import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence, type Variants } from 'framer-motion'
import { useMotionPreset, type MotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'

interface LoadingVerbProps {
  className?: string
  /** Milliseconds each verb is shown before cross-fading to the next. */
  interval?: number
  /** Accessible label for screen readers. */
  'aria-label'?: string
}

const VERBS = [
  'Brewing',
  'Cogitating',
  'Conjuring',
  'Dreaming',
  'Fermenting',
  'Gestating',
  'Hatching',
  'Ideating',
  'Incubating',
  'Jiving',
  'Marinating',
  'Musing',
  'Percolating',
  'Pondering',
  'Ruminating',
  'Simmering',
  'Sondering',
  'Stewing',
  'Tinkering',
  'Weaving',
  'Whittling',
]

function nextVerb(prev: string): string {
  let candidate = prev
  if (VERBS.length < 2) return VERBS[0]
  while (candidate === prev) {
    candidate = VERBS[Math.floor(Math.random() * VERBS.length)]
  }
  return candidate
}

function containerVariants(preset: MotionPreset): Variants {
  return {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: preset.stagger,
        delayChildren: 0.05 * preset.scale,
      },
    },
    exit: {
      opacity: 0,
      transition: {
        staggerChildren: preset.stagger * 0.6,
        staggerDirection: -1,
        duration: 0.15 * preset.scale,
      },
    },
  }
}

function letterVariants(preset: MotionPreset): Variants {
  const travel = 8 * preset.distance
  return {
    hidden: { opacity: 0, y: travel },
    visible: {
      opacity: 1,
      y: 0,
      transition: preset.transition,
    },
    exit: {
      opacity: 0,
      y: -travel * 0.75,
      transition: { duration: 0.2 * preset.scale, ease: 'easeIn' },
    },
  }
}

function StaticVerb({
  verb,
  className,
  ariaLabel,
}: {
  verb: string
  className?: string
  ariaLabel: string
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-2 text-sm text-(--color-text-muted) select-none',
        className,
      )}
      role="status"
      aria-label={ariaLabel}
    >
      <span>{verb}...</span>
    </span>
  )
}

export function LoadingVerb({
  className,
  interval = 2_800,
  'aria-label': ariaLabel = 'Thinking',
}: LoadingVerbProps) {
  const preset = useMotionPreset()
  const [verb, setVerb] = useState(() => VERBS[Math.floor(Math.random() * VERBS.length)])
  const [key, setKey] = useState(0)

  const containers = useMemo(() => containerVariants(preset), [preset])
  const letters = useMemo(() => letterVariants(preset), [preset])

  useEffect(() => {
    const id = setInterval(() => {
      setVerb((prev) => nextVerb(prev))
      setKey((p) => p + 1)
    }, interval)
    return () => clearInterval(id)
  }, [interval])

  if (preset.intensity === 'reduced') {
    return <StaticVerb verb={verb} className={className} ariaLabel={ariaLabel} />
  }

  return (
    <span
      className={cn(
        'inline-flex items-center gap-2 text-sm text-(--color-text-muted) select-none',
        className,
      )}
      role="status"
      aria-label={ariaLabel}
    >
      <AnimatePresence mode="wait">
        <motion.span
          key={key}
          variants={containers}
          initial="hidden"
          animate="visible"
          exit="exit"
          className="inline-flex"
        >
          {verb.split('').map((letter, i) => (
            <motion.span
              key={`${key}-${i}`}
              variants={letters}
              className="inline-block"
            >
              {letter}
            </motion.span>
          ))}
        </motion.span>
      </AnimatePresence>

      <span className="inline-flex items-center gap-[3px]">
        {[0, 1, 2].map((i) =>
          preset.ambient ? (
            <motion.span
              key={i}
              className="h-[3px] w-[3px] rounded-full bg-(--color-text-muted)"
              animate={{ opacity: [0.3, 0.8, 0.3] }}
              transition={{
                duration: 1.8 * preset.scale,
                repeat: Infinity,
                delay: i * 0.25 * preset.scale,
                ease: 'easeInOut',
              }}
            />
          ) : (
            <span
              key={i}
              className="h-[3px] w-[3px] rounded-full bg-(--color-text-muted)"
              style={{ opacity: 0.45 }}
            />
          ),
        )}
      </span>
    </span>
  )
}
