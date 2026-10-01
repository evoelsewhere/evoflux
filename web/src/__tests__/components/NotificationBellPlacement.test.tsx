/**
 * Notification bell placement.
 *
 * On Windows the bell lives in the window title bar, left of the
 * minimize/maximize/close caption buttons (WindowsTitleBar), and the workbench
 * top bar does not render a second one while that title bar is active.
 */
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { WindowsTitleBar } from '@/components/WindowsTitleBar'
import { MacTitleBar } from '@/components/MacTitleBar'
import { WorkbenchBar } from '@/components/workbench/WorkbenchBar'

const platform = vi.hoisted(() => ({ isWindowsTitleBar: false, isMacOverlay: false }))

vi.mock('@/hooks/use-platform', () => ({
  usePlatform: () => ({
    isTauri: true,
    os: platform.isMacOverlay ? 'macos' : 'windows',
    isWindowsTitleBar: platform.isWindowsTitleBar,
    isMacOverlay: platform.isMacOverlay,
  }),
}))
vi.mock('@/hooks/use-tauri-drag', () => ({ useTauriDrag: () => ({}) }))
vi.mock('@/hooks/use-window-history', () => ({
  useWindowHistory: () => ({
    canGoBack: false,
    canGoForward: false,
    back: vi.fn(),
    forward: vi.fn(),
    hasAppSidebar: true,
    sidebarCollapsed: false,
  }),
}))
vi.mock('@/hooks/useDesktopSettings', () => ({
  useDesktopSettings: () => ({ data: { tray_icon: true } }),
}))
vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }))
vi.mock('@tauri-apps/api/dpi', () => ({ LogicalPosition: class {} }))
vi.mock('@tauri-apps/api/menu', () => ({
  Menu: { new: vi.fn() },
  MenuItem: { new: vi.fn() },
  PredefinedMenuItem: { new: vi.fn() },
  Submenu: { new: vi.fn() },
}))
vi.mock('@tauri-apps/api/window', () => ({
  getCurrentWindow: () => ({
    isMaximized: vi.fn().mockResolvedValue(false),
    onResized: vi.fn().mockResolvedValue(vi.fn()),
    minimize: vi.fn(),
    toggleMaximize: vi.fn(),
    close: vi.fn(),
  }),
}))
vi.mock('@/queries', () => ({
  useRegistryQuery: () => ({ data: undefined }),
  useWebBridgeSettingsQuery: () => ({ data: { enabled: true, allow_evaluate: true } }),
}))
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  getWebBridgeStatus: vi.fn().mockResolvedValue({ connected: false, extensions: [] }),
}))

function renderWorkbenchBar({ isMacOverlay = false }: { isMacOverlay?: boolean } = {}) {
  return render(
    <WorkbenchBar
      activeAgent="Lead"
      leadName="Lead"
      leadOptions={[{ name: 'Lead', description: null, model: null, is_default: true, members: [] }]}
      leadChanging={false}
      onLeadChange={vi.fn()}
      viewMode="agent"
      onViewModeChange={vi.fn()}
      onOpenMobileSidebar={vi.fn()}
      isMobile={false}
      isMacOverlay={isMacOverlay}
      mode="work"
      webBridgeEnabled={false}
      onWebBridgeEnabledChange={vi.fn()}
      webBridgePopoverOpen={false}
      onWebBridgePopoverOpenChange={vi.fn()}
    />,
  )
}

describe('Notification bell placement', () => {
  beforeEach(() => {
    platform.isWindowsTitleBar = true
    platform.isMacOverlay = false
    window.matchMedia ??= ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    })) as typeof window.matchMedia
  })

  it('renders the bell in the Windows title bar, left of the caption buttons', () => {
    render(<WindowsTitleBar />)

    const bell = screen.getByRole('button', { name: /Notifications/ })
    const minimize = screen.getByRole('button', { name: 'Minimize' })
    const close = screen.getByRole('button', { name: 'Close' })

    expect(bell.compareDocumentPosition(minimize) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(bell.compareDocumentPosition(close) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('hides the bell in the workbench top bar while the Windows title bar owns it', () => {
    renderWorkbenchBar()

    expect(screen.queryByRole('button', { name: /Notifications/ })).not.toBeInTheDocument()
  })

  it('keeps the bell in the workbench top bar when no Windows title bar is active', () => {
    platform.isWindowsTitleBar = false
    renderWorkbenchBar()

    expect(screen.getByRole('button', { name: /Notifications/ })).toBeInTheDocument()
  })

  it('renders the bell in the macOS title-bar strip, right of the traffic lights', () => {
    platform.isWindowsTitleBar = false
    platform.isMacOverlay = true
    render(<MacTitleBar />)

    const bell = screen.getByRole('button', { name: /Notifications/ })
    const sidebar = screen.getByRole('button', { name: /sidebar/i })

    // Traffic lights are native; the bell is the first app control after them.
    expect(bell.compareDocumentPosition(sidebar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('hides the bell in the workbench top bar while the macOS title bar owns it', () => {
    platform.isMacOverlay = true
    renderWorkbenchBar({ isMacOverlay: true })

    expect(screen.queryByRole('button', { name: /Notifications/ })).not.toBeInTheDocument()
  })
})
