import { useState } from 'react'

/**
 * Run `reset` during render when `value` changes, instead of after commit.
 *
 * This is React's documented way to adjust state in response to a prop or
 * derived value changing. The obvious alternative —
 *
 *     useEffect(() => { setThing(null) }, [value])
 *
 * — is a render worse: React commits the stale state, paints it, then runs
 * the effect and renders again. Doing it during render lets React discard the
 * in-progress output and retry before anything reaches the screen, which is
 * why the `react-hooks/set-state-in-effect` rule flags the effect form.
 *
 * `reset` may only touch state owned by the calling component. Setting state
 * on a *different* component during render is a genuine error, and no amount
 * of moving it around fixes that.
 */
export function useResetOnChange<T>(value: T, reset: () => void): void {
  const [previous, setPrevious] = useState(value)
  if (!Object.is(previous, value)) {
    setPrevious(value)
    reset()
  }
}
