import { useSyncExternalStore } from 'react'

// ── Shared live clock ────────────────────────────────────────────────────────
// A single interval drives *all* elapsed timers so React can batch every
// subscriber update into one render. The clock auto-starts on first
// subscription, pauses while the document is hidden, and tears down — both the
// interval *and* the visibilitychange listener — once the last subscriber
// leaves. Tearing down only the interval leaks a listener per start/stop
// cycle, and a long conversation runs through many of those.
//
// 250 ms rather than 1 s: `formatDuration` renders one decimal place below
// 10 s, which is where most tool calls land, so a 1 s tick makes the tenths
// digit jump a whole second at a time. This still cuts timer wakeups by 40×
// versus a per-instance 100 ms interval.
//
// Its own module rather than living in `ToolCall/index.tsx`: a file that
// exports both components and plain functions loses fast refresh for every
// component in it.
const CLOCK_INTERVAL_MS = 250

let _clockInterval: ReturnType<typeof setInterval> | null = null
let _clockOnVisibility: (() => void) | null = null
const _clockListeners = new Set<(now: number) => void>()

/** Latest published tick. `useSyncExternalStore` compares snapshots with
 *  `Object.is`, so this has to be a stored value — returning a fresh
 *  `Date.now()` from `getSnapshot` would re-render forever. */
let _now = Date.now()

function startClock() {
  if (_clockInterval !== null || typeof window === 'undefined') return
  const tick = () => {
    if (typeof document !== 'undefined' && document.hidden) return
    _now = Date.now()
    _clockListeners.forEach((fn) => fn(_now))
  }
  _clockInterval = setInterval(tick, CLOCK_INTERVAL_MS)
  if (typeof document !== 'undefined') {
    // Catch up immediately when the tab comes back to the foreground.
    _clockOnVisibility = tick
    document.addEventListener('visibilitychange', tick)
  }
}

function stopClock() {
  if (_clockInterval !== null) {
    clearInterval(_clockInterval)
    _clockInterval = null
  }
  if (_clockOnVisibility !== null) {
    document.removeEventListener('visibilitychange', _clockOnVisibility)
    _clockOnVisibility = null
  }
}

export function subscribeClock(listener: (now: number) => void) {
  // Refresh before the first read. The clock freezes while nobody is
  // watching, so a subscriber arriving after a quiet spell would otherwise
  // render one stale tick — up to `CLOCK_INTERVAL_MS` of wrong elapsed time.
  _now = Date.now()
  _clockListeners.add(listener)
  startClock()
  return () => {
    _clockListeners.delete(listener)
    if (_clockListeners.size === 0) stopClock()
  }
}

function subscribeNothing() {
  return () => {}
}

function getNow() {
  return _now
}

/**
 * Subscribe to the shared clock; it pauses in background tabs.
 *
 * `useSyncExternalStore` rather than `useState` + `useEffect`: the clock is an
 * external store, and reading it that way drops the re-sync-on-subscribe
 * `setState` that ran on every mount — a second render before the first paint,
 * every time a tool call appeared.
 */
export function useLiveClock(enabled: boolean): number {
  return useSyncExternalStore(
    enabled ? subscribeClock : subscribeNothing,
    getNow,
    getNow,
  )
}
