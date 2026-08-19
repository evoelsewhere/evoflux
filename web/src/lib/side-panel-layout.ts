export const SIDE_PANEL_LAYOUT = {
  maxViewportRatio: 0.42,
  minPrimaryWidth: 480,
  shellChromeWidth: 32,
} as const

interface ResponsiveSidePanelInput {
  viewportWidth: number
  sidebarWidth: number
  sidebarCollapsed: boolean
  sidebarOverlay: boolean
  minWidth: number
  maxWidth: number
  canOverlay: boolean
  inFlow: boolean
}

export interface ResponsiveSidePanelLayout {
  overlay: boolean
  maxWidth: number
}

/** Keep docked panels proportional while reserving a readable primary column. */
export function getResponsiveSidePanelLayout({
  viewportWidth,
  sidebarWidth,
  sidebarCollapsed,
  sidebarOverlay,
  minWidth,
  maxWidth,
  canOverlay,
  inFlow,
}: ResponsiveSidePanelInput): ResponsiveSidePanelLayout {
  if (!inFlow) return { overlay: false, maxWidth }

  const safeViewportWidth = Math.max(0, Math.round(viewportWidth))
  const sidebarFootprint = sidebarCollapsed || sidebarOverlay ? 0 : sidebarWidth
  const availableForPanel = Math.floor(Math.min(
    safeViewportWidth * SIDE_PANEL_LAYOUT.maxViewportRatio,
    safeViewportWidth
      - sidebarFootprint
      - SIDE_PANEL_LAYOUT.minPrimaryWidth
      - SIDE_PANEL_LAYOUT.shellChromeWidth,
  ))

  if (canOverlay && availableForPanel < minWidth) {
    return { overlay: true, maxWidth }
  }

  return {
    overlay: false,
    maxWidth: Math.max(minWidth, Math.min(maxWidth, availableForPanel)),
  }
}
