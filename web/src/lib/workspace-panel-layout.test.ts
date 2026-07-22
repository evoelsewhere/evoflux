import { describe, expect, it } from 'vitest'
import { getWorkspacePanelLayout } from './workspace-panel-layout'

describe('workspace panel layout', () => {
  it.each([375, 768, 1024])('uses a full-screen non-resizable overlay at %ipx without clamping the saved docked width', (viewportWidth) => {
    expect(getWorkspacePanelLayout({ viewportWidth, sidebarWidth: 280, sidebarCollapsed: false })).toEqual({
      mode: 'overlay',
      defaultWidth: 480,
      minWidth: 480,
      maxWidth: 960,
      resizable: false,
    })
  })

  it('docks at 1440px while reserving at least 520px for chat', () => {
    const layout = getWorkspacePanelLayout({ viewportWidth: 1440, sidebarWidth: 280, sidebarCollapsed: false })

    expect(layout.mode).toBe('docked')
    expect(layout.minWidth).toBe(480)
    expect(layout.defaultWidth).toBe(576)
    expect(layout.maxWidth).toBe(599)
    expect(1440 - 280 - 40 - layout.maxWidth).toBeGreaterThanOrEqual(521)
    expect(layout.resizable).toBe(true)
  })

  it('caps the docked default at 720px and the maximum at 960px', () => {
    expect(getWorkspacePanelLayout({ viewportWidth: 1920, sidebarWidth: 280, sidebarCollapsed: false })).toEqual({
      mode: 'docked',
      defaultWidth: 720,
      minWidth: 480,
      maxWidth: 960,
      resizable: true,
    })
  })

  it('uses the collapsed rail footprint when deciding whether docking fits', () => {
    const expanded = getWorkspacePanelLayout({ viewportWidth: 1280, sidebarWidth: 280, sidebarCollapsed: false })
    const collapsed = getWorkspacePanelLayout({ viewportWidth: 1280, sidebarWidth: 280, sidebarCollapsed: true })

    expect(expanded.mode).toBe('overlay')
    expect(collapsed.mode).toBe('docked')
  })
})
