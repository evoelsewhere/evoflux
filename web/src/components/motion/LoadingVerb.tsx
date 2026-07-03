/**
 * LoadingVerb — Claude-style whimsical gerund indicator.
 *
 * Rotates through playful single-word actions (Brewing, Ruminating,
 * Tinkering …) with a clean fade transition. Pair with the EvoFlux
 * logo + agent name label for the full loading experience.
 *
 * Respects `prefers-reduced-motion` by disabling the fade animation
 * and just swapping the text instantly.
 */
import { useEffect, useState } from 'react'
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
  // Guard against the extremely unlikely but possible infinite loop when
  // VERBS has only one entry.
  if (VERBS.length < 2) return VERBS[0]
  while (candidate === prev) {
    candidate = VERBS[Math.floor(Math.random() * VERBS.length)]
  }
  return candidate
}

export function LoadingVerb({
  className,
  interval = 2_800,
  'aria-label': ariaLabel = 'Thinking',
}: LoadingVerbProps) {
  const [verb, setVerb] = useState(() => VERBS[Math.floor(Math.random() * VERBS.length)])
  const [fading, setFading] = useState(false)

  useEffect(() => {
    const id = setInterval(() => {
      setFading(true)
      // Swap the text mid-fade so the new word fades *in* while the old
      // one fades *out*. The CSS transition duration is 400ms; we swap
      // at the halfway mark.
      setTimeout(() => {
        setVerb((prev) => nextVerb(prev))
        setFading(false)
      }, 200)
    }, interval)
    return () => clearInterval(id)
  }, [interval])

  return (
    <span
      className={cn(
        'inline-flex items-center gap-2 text-sm text-(--color-text-muted) select-none',
        className,
      )}
      role="status"
      aria-label={ariaLabel}
    >
      <span
        className={cn(
          'loading-verb transition-opacity duration-400',
          fading ? 'opacity-0' : 'opacity-100',
        )}
      >
        {verb}...
      </span>
    </span>
  )
}
