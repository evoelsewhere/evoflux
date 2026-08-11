import type { ViewMode } from './types'
import {
  MIN_PRIMARY_COLUMN_WIDTH,
  WORKSPACE_PANEL,
} from '@/lib/workspace-panel-layout'

export const AUTO_SPLIT_ACTIVE_AGENT_THRESHOLD = 2

interface AutomaticSplitDecision {
  previousActiveCount: number
  activeCount: number
  viewMode: ViewMode
  isMobile: boolean
}

interface AdaptiveSidebarOverlayDecision {
  workbenchOpen: boolean
  isMobile: boolean
  sidebarMode: 'docked' | 'overlay'
  sidebarCollapsed: boolean
  mainWidth: number
  sidebarWidth: number
  macOverlay?: boolean
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
 * Switch navigation to a non-layout drawer when an expanded docked sidebar
 * would leave too little room for the primary conversation. Estimating the
 * expanded docked width in both modes keeps the decision stable: removing the
 * sidebar from flex layout must not immediately switch it back again.
 */
export function shouldUseSidebarOverlay({
  workbenchOpen,
  isMobile,
  sidebarMode,
  sidebarCollapsed,
  mainWidth,
  sidebarWidth,
  macOverlay = false,
}: AdaptiveSidebarOverlayDecision): boolean {
  if (!workbenchOpen || isMobile) return false

  const collapsedWidth = macOverlay
    ? WORKSPACE_PANEL.macCollapsedRailWidth
    : WORKSPACE_PANEL.collapsedRailWidth
  const expandedDockedMainWidth = sidebarMode === 'overlay'
    ? mainWidth - sidebarWidth - WORKSPACE_PANEL.shellChromeWidth
    : mainWidth - (sidebarCollapsed ? Math.max(0, sidebarWidth - collapsedWidth) : 0)

  return (
    expandedDockedMainWidth < MIN_PRIMARY_COLUMN_WIDTH
  )
}
