export const HISTORY_INITIAL_RENDERED_TURNS = 72
export const HISTORY_RENDER_STEP = 24

const HISTORY_LOAD_MINIMUM_PX = 1_600
const HISTORY_LOAD_VIEWPORTS = 3
const HISTORY_REARM_MINIMUM_PX = 800

/** Start preparing earlier history while several screens still remain above. */
export function historyLoadThreshold(clientHeight: number): number {
  return Math.max(
    HISTORY_LOAD_MINIMUM_PX,
    Math.round(Math.max(0, clientHeight) * HISTORY_LOAD_VIEWPORTS),
  )
}

/** Rearm after prepend once the restored viewport has a fresh screen of buffer. */
export function historyLoadRearmThreshold(clientHeight: number): number {
  return historyLoadThreshold(clientHeight) + Math.max(
    HISTORY_REARM_MINIMUM_PX,
    Math.round(Math.max(0, clientHeight)),
  )
}

export function shouldPrimeOlderHistory({
  canLoadOlder,
  clientHeight,
  scrollHeight,
}: {
  canLoadOlder: boolean
  clientHeight: number
  scrollHeight: number
}): boolean {
  if (!canLoadOlder) return false
  const upwardBuffer = Math.max(0, scrollHeight - clientHeight)
  return upwardBuffer <= historyLoadThreshold(clientHeight)
}
