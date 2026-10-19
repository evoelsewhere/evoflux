import {
  MIN_PRIMARY_COLUMN_WIDTH,
  WORKSPACE_PANEL,
} from '@/lib/workspace-panel-layout'

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
}: AdaptiveSidebarOverlayDecision): boolean {
  if (!workbenchOpen || isMobile) return false

  const expandedDockedMainWidth = sidebarMode === 'overlay'
    ? mainWidth - sidebarWidth - WORKSPACE_PANEL.shellChromeWidth
    : mainWidth - (sidebarCollapsed ? sidebarWidth : 0)

  return (
    expandedDockedMainWidth < MIN_PRIMARY_COLUMN_WIDTH
  )
}
