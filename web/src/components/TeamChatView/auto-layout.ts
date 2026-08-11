import type { ViewMode } from './types'
import { MIN_PRIMARY_COLUMN_WIDTH } from '@/lib/workspace-panel-layout'

export const AUTO_SPLIT_ACTIVE_AGENT_THRESHOLD = 2

interface AutomaticSplitDecision {
  previousActiveCount: number
  activeCount: number
  viewMode: ViewMode
  isMobile: boolean
}

interface AutomaticSidebarCollapseDecision {
  workbenchOpen: boolean
  isMobile: boolean
  sidebarCollapsed: boolean
  mainWidth: number
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

/**
 * Keep the primary conversation usable as the right-hand Workbench opens or
 * grows. This is intentionally one-way: closing or shrinking the Workbench
 * does not override a sidebar state the user may now prefer.
 */
export function shouldAutoCollapseSidebar({
  workbenchOpen,
  isMobile,
  sidebarCollapsed,
  mainWidth,
}: AutomaticSidebarCollapseDecision): boolean {
  return (
    workbenchOpen
    && !isMobile
    && !sidebarCollapsed
    && mainWidth < MIN_PRIMARY_COLUMN_WIDTH
  )
}
