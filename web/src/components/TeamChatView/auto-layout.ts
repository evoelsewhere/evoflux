import type { ViewMode } from './types'

export const AUTO_SPLIT_ACTIVE_AGENT_THRESHOLD = 2

interface AutomaticSplitDecision {
  previousActiveCount: number
  activeCount: number
  viewMode: ViewMode
  isMobile: boolean
}

/**
 * Auto-split only on the threshold crossing. This lets a user return to Agent
 * view manually while the same team is still running without immediately
 * being forced back into Split.
 */
export function shouldStartAutomaticSplit({
  previousActiveCount,
  activeCount,
  viewMode,
  isMobile,
}: AutomaticSplitDecision): boolean {
  return (
    !isMobile
    && viewMode === 'agent'
    && previousActiveCount <= AUTO_SPLIT_ACTIVE_AGENT_THRESHOLD
    && activeCount > AUTO_SPLIT_ACTIVE_AGENT_THRESHOLD
  )
}
