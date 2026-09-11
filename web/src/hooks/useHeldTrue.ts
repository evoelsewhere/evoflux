import { useEffect, useState } from 'react'

/**
 * `value`, but a fall to false is held for `holdMs` before it lands.
 *
 * A turn is not one continuous "working" run: an agent activation ends, the
 * stream flushes, and the next activation starts a moment later. Measured in
 * the app, that gap ran ~1.2s, and anything keyed directly on the working
 * flag blinked out and back in the middle of what the reader experiences as
 * one answer. Holding the fall bridges the gap; a turn that really has ended
 * settles `holdMs` later, which the caller can spend on an exit animation.
 */
export function useHeldTrue(value: boolean, holdMs: number): boolean {
  const [held, setHeld] = useState(value)

  // Rising edges land during render — the line must appear on the same paint
  // as the work it reports, not a frame later.
  if (value && !held) setHeld(true)

  useEffect(() => {
    if (value) return undefined
    const timer = window.setTimeout(() => setHeld(false), holdMs)
    return () => window.clearTimeout(timer)
  }, [value, holdMs])

  return held
}
