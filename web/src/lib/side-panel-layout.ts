export const SIDE_PANEL_LAYOUT = {
  maxViewportRatio: 0.42,
  /**
   * Surfaces that render someone else's page — the in-app browser — rather
   * than our own chrome. A chat-sized share turns every site into its
   * tablet layout, so they get a larger one.
   */
  contentViewportRatio: 0.62,
  /**
   * The workbench dock holds documents, slides and code as well as the
   * browser, so it may take most of the window; the primary column still
   * keeps `minPrimaryWidth`.
   */
  workbenchViewportRatio: 0.75,
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
  /** Share of the viewport this panel may claim. Defaults to `maxViewportRatio`. */
  viewportRatio?: number
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
  viewportRatio = SIDE_PANEL_LAYOUT.maxViewportRatio,
}: ResponsiveSidePanelInput): ResponsiveSidePanelLayout {
  if (!inFlow) return { overlay: false, maxWidth }

  const safeViewportWidth = Math.max(0, Math.round(viewportWidth))
  const sidebarFootprint = sidebarCollapsed || sidebarOverlay ? 0 : sidebarWidth
  const availableForPanel = Math.floor(Math.min(
    safeViewportWidth * viewportRatio,
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
