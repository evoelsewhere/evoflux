export const MIN_PRIMARY_COLUMN_WIDTH = 521

export const WORKSPACE_PANEL = {
  minWidth: 480,
  maxWidth: 960,
  maxDefaultWidth: 720,
  // One extra CSS pixel absorbs fractional shell borders at desktop scale,
  // keeping the rendered primary column at or above the 520px contract.
  minPrimaryWidth: MIN_PRIMARY_COLUMN_WIDTH,
  collapsedRailWidth: 56,
  macCollapsedRailWidth: 70,
  shellChromeWidth: 40,
} as const

interface WorkspacePanelLayoutInput {
  viewportWidth: number
  sidebarWidth: number
  sidebarCollapsed: boolean
  macOverlay?: boolean
}

export interface WorkspacePanelLayout {
  mode: 'docked' | 'overlay'
  defaultWidth: number
  minWidth: number
  maxWidth: number
  resizable: boolean
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

export function getWorkspacePanelLayout({
  viewportWidth,
  sidebarWidth,
  sidebarCollapsed,
  macOverlay = false,
}: WorkspacePanelLayoutInput): WorkspacePanelLayout {
  const safeViewportWidth = Math.max(0, Math.round(viewportWidth))
  const sidebarFootprint = sidebarCollapsed
    ? macOverlay ? WORKSPACE_PANEL.macCollapsedRailWidth : WORKSPACE_PANEL.collapsedRailWidth
    : sidebarWidth
  const availableWidth = Math.max(
    0,
    safeViewportWidth - sidebarFootprint - WORKSPACE_PANEL.shellChromeWidth,
  )
  const maxDockedWidth = Math.min(
    WORKSPACE_PANEL.maxWidth,
    availableWidth - WORKSPACE_PANEL.minPrimaryWidth,
  )

  if (maxDockedWidth < WORKSPACE_PANEL.minWidth) {
    return {
      mode: 'overlay',
      // Visual width is 100vw in SidePanel. Stable docked constraints keep
      // a saved desktop width intact while the responsive overlay is active.
      defaultWidth: clamp(
        Math.round(safeViewportWidth * 0.4),
        WORKSPACE_PANEL.minWidth,
        WORKSPACE_PANEL.maxDefaultWidth,
      ),
      minWidth: WORKSPACE_PANEL.minWidth,
      maxWidth: WORKSPACE_PANEL.maxWidth,
      resizable: false,
    }
  }

  return {
    mode: 'docked',
    defaultWidth: clamp(
      Math.round(safeViewportWidth * 0.4),
      WORKSPACE_PANEL.minWidth,
      Math.min(WORKSPACE_PANEL.maxDefaultWidth, maxDockedWidth),
    ),
    minWidth: WORKSPACE_PANEL.minWidth,
    maxWidth: maxDockedWidth,
    resizable: true,
  }
}
