import * as React from "react"

// Mirrors Tailwind's `md:` boundary (min-width: 768px) from the other side,
// so a fractional viewport width — browser zoom, Windows display scaling —
// can never disagree with the CSS that renders alongside this hook.
const MOBILE_QUERY = "(max-width: 767.98px)"

let cached: MediaQueryList | null = null

function mediaQuery(): MediaQueryList {
  if (!cached) cached = window.matchMedia(MOBILE_QUERY)
  return cached
}

// Snapshot and subscription MUST read the same MediaQueryList: deriving the
// snapshot from `window.innerWidth` instead let the value go stale, because
// resizing between two widths that both fail the query fires no change event
// and therefore never notifies React of the new snapshot.
function getIsMobile(): boolean {
  return mediaQuery().matches
}

function subscribeIsMobile(onChange: () => void): () => void {
  const mql = mediaQuery()
  mql.addEventListener("change", onChange)
  return () => mql.removeEventListener("change", onChange)
}

export function useIsMobile() {
  return React.useSyncExternalStore(subscribeIsMobile, getIsMobile, () => false)
}
