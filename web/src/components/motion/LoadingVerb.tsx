/**
 * LoadingVerb — Whimsical gerund indicator.
 *
 * Rotates through playful single-word actions (Brewing, Ruminating,
 * Tinkering …) with smooth, gentle letter-by-letter transitions.
 *
 * Respects `prefers-reduced-motion` by disabling animations
 * and just swapping the text instantly.
 */
import { useEffect, useState } from 'react'
import { motion, AnimatePresence, type Variants } from 'framer-motion'
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

/**
 * Pick a random verb that differs from `prev`.
 */
function nextVerb(prev: string): string {
  let candidate = prev
  if (VERBS.length < 2) return VERBS[0]
  while (candidate === prev) {
    candidate = VERBS[Math.floor(Math.random() * VERBS.length)]
  }
  return candidate
}

/* ─── animation variants ─── */

const containerVariants: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.04,
      delayChildren: 0.05,
    },
  },
  exit: {
    opacity: 0,
    transition: {
      staggerChildren: 0.025,
      staggerDirection: -1,
      duration: 0.15,
    },
  },
}

const letterVariants: Variants = {
  hidden: { opacity: 0, y: 8 },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.35,
      ease: [0.25, 0.1, 0.25, 1],
    },
  },
  exit: {
    opacity: 0,
    y: -6,
    transition: { duration: 0.2, ease: 'easeIn' },
  },
}

const dotVariants: Variants = {
  initial: { opacity: 0.3 },
  animate: (i: number) => ({
    opacity: [0.3, 0.8, 0.3],
    transition: {
      duration: 1.8,
      repeat: Infinity,
      delay: i * 0.25,
      ease: 'easeInOut',
    },
  }),
}

/* ─── component ─── */

export function LoadingVerb({
  className,
  interval = 2_800,
  'aria-label': ariaLabel = 'Thinking',
}: LoadingVerbProps) {
  const [verb, setVerb] = useState(() => VERBS[Math.floor(Math.random() * VERBS.length)])
  const [key, setKey] = useState(0)
  const prefersReducedMotion =
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches

  useEffect(() => {
    const id = setInterval(() => {
      setVerb((prev) => nextVerb(prev))
      setKey((p) => p + 1)
    }, interval)
    return () => clearInterval(id)
  }, [interval])

  if (prefersReducedMotion) {
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

  return (
    <span
      className={cn(
        'inline-flex items-center gap-2 text-sm text-(--color-text-muted) select-none',
        className,
      )}
      role="status"
      aria-label={ariaLabel}
    >
      {/* Letter-by-letter verb */}
      <AnimatePresence mode="wait">
        <motion.span
          key={key}
          variants={containerVariants}
          initial="hidden"
          animate="visible"
          exit="exit"
          className="inline-flex"
        >
          {verb.split('').map((letter, i) => (
            <motion.span
              key={`${key}-${i}`}
              variants={letterVariants}
              className="inline-block"
            >
              {letter}
            </motion.span>
          ))}
        </motion.span>
      </AnimatePresence>

      {/* Gentle pulsing dots */}
      <span className="inline-flex items-center gap-[3px]">
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="w-[3px] h-[3px] rounded-full bg-(--color-text-muted)"
            custom={i}
            variants={dotVariants}
            initial="initial"
            animate="animate"
          />
        ))}
      </span>
    </span>
  )
}