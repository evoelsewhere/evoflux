import { describe, expect, it } from 'vitest'

import {
  getResponsiveSidePanelLayout,
  SIDE_PANEL_LAYOUT,
} from '@/lib/side-panel-layout'

const base = {
  sidebarWidth: 280,
  sidebarCollapsed: false,
  sidebarOverlay: false,
  minWidth: 320,
  maxWidth: 600,
  canOverlay: true,
  inFlow: true,
}

describe('getResponsiveSidePanelLayout', () => {
  it('keeps the configured maximum on a wide window', () => {
    expect(getResponsiveSidePanelLayout({ ...base, viewportWidth: 1600 }))
      .toEqual({ overlay: false, maxWidth: 600 })
  })

  it('shrinks the panel to preserve the primary content column', () => {
    expect(getResponsiveSidePanelLayout({ ...base, viewportWidth: 1200 }))
      .toEqual({ overlay: false, maxWidth: 408 })
  })

  it('gives a content surface a larger share of the same window', () => {
    // 1920 × 0.42 = 806 for tool chrome; the browser earns 0.62 up to the
    // width the primary column can spare.
    expect(getResponsiveSidePanelLayout({
      ...base,
      viewportWidth: 1920,
      maxWidth: 1600,
    })).toEqual({ overlay: false, maxWidth: 806 })

    expect(getResponsiveSidePanelLayout({
      ...base,
      viewportWidth: 1920,
      maxWidth: 1600,
      viewportRatio: SIDE_PANEL_LAYOUT.contentViewportRatio,
    })).toEqual({ overlay: false, maxWidth: 1128 })
  })

  it('does not reserve space for a sidebar already rendered as an overlay', () => {
    expect(getResponsiveSidePanelLayout({
      ...base,
      viewportWidth: 1000,
      sidebarOverlay: true,
    })).toEqual({ overlay: false, maxWidth: 420 })
  })

  it('switches responsive panels to overlay when docking would be cramped', () => {
    expect(getResponsiveSidePanelLayout({
      ...base,
      viewportWidth: 800,
      sidebarOverlay: true,
    })).toEqual({ overlay: true, maxWidth: 600 })
  })

  it('leaves parent-owned panel geometry untouched', () => {
    expect(getResponsiveSidePanelLayout({
      ...base,
      viewportWidth: 800,
      inFlow: false,
    })).toEqual({ overlay: false, maxWidth: 600 })
  })
})
