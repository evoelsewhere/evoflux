import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { WorkbenchBar } from '@/components/workbench/WorkbenchBar'

const webBridgeApi = vi.hoisted(() => ({
  getWebBridgeStatus: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  getWebBridgeStatus: webBridgeApi.getWebBridgeStatus,
}))

vi.mock('@/queries', () => ({
  useRegistryQuery: () => ({ data: undefined }),
  useWebBridgeSettingsQuery: () => ({ data: { enabled: true, allow_evaluate: true } }),
}))

describe('WorkbenchBar browser access control', () => {
  beforeEach(() => {
    webBridgeApi.getWebBridgeStatus.mockReset().mockResolvedValue({
      connected: true,
      extensions: [
        {
          extension_id: 'extension-1',
          browser: 'Chrome',
          version: '1.0.0',
          protocol_version: 1,
          capabilities: {},
          connected_at: Date.now(),
          current_url: '',
          current_title: '',
        },
      ],
    })
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    })
  })

  function renderBar(
    enabled: boolean,
    onChange = vi.fn(),
    popoverOpen = false,
    onPopoverOpenChange = vi.fn(),
    onViewModeChange = vi.fn(),
  ) {
    render(
      <WorkbenchBar
        activeAgent="Lead"
        leadName="Lead"
        leadOptions={[{ name: 'Lead', description: null, model: null, is_default: true, members: [] }]}
        leadChanging={false}
        onLeadChange={vi.fn()}
        viewMode="agent"
        onViewModeChange={onViewModeChange}
        onOpenMobileSidebar={vi.fn()}
        isMobile={false}
        isMacOverlay={false}
        mode="work"
        webBridgeEnabled={enabled}
        onWebBridgeEnabledChange={onChange}
        webBridgePopoverOpen={popoverOpen}
        onWebBridgePopoverOpenChange={onPopoverOpenChange}
      />,
    )
    return { onChange, onPopoverOpenChange, onViewModeChange }
  }

  it('opens WebBridge settings from the top bar without enabling it immediately', () => {
    const { onChange, onPopoverOpenChange } = renderBar(false)
    const control = screen.getByRole('button', { name: 'Open WebBridge' })

    expect(control).toHaveTextContent('WebBridge')
    expect(screen.getByRole('button', { name: 'Select lead agent' }).closest('header')).toHaveClass('pl-12')

    fireEvent.click(control)
    expect(onPopoverOpenChange.mock.calls[0]?.[0]).toBe(true)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('dispatches a conversation layout selection on the first click', async () => {
    const onViewModeChange = vi.fn()
    renderBar(false, vi.fn(), false, vi.fn(), onViewModeChange)

    fireEvent.click(screen.getByRole('button', { name: 'Choose conversation layout' }))
    fireEvent.click(await screen.findByText('Split'))

    expect(onViewModeChange).toHaveBeenCalledOnce()
    expect(onViewModeChange).toHaveBeenCalledWith('split')
  })

  it('turns WebBridge on for agent browsing from the popover', async () => {
    const onChange = vi.fn()
    renderBar(false, onChange, true)
    const enableButton = screen.getByRole('button', { name: 'Turn on WebBridge for agent browsing' })

    expect(enableButton).toBeEnabled()
    expect(enableButton.closest('[data-slot="popover-content"]')).toHaveAttribute('data-no-drag')
    fireEvent.click(enableButton)
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it('can be turned on before the extension connects', async () => {
    webBridgeApi.getWebBridgeStatus.mockResolvedValue({ connected: false, extensions: [] })
    const onChange = vi.fn()
    renderBar(false, onChange, true)
    const enableButton = screen.getByRole('button', { name: 'Turn on WebBridge for agent browsing' })

    fireEvent.click(enableButton)
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it('keeps the saved toggle on through a disconnect and says where agents browse', async () => {
    webBridgeApi.getWebBridgeStatus.mockResolvedValue({ connected: false, extensions: [] })
    const onChange = vi.fn()
    renderBar(true, onChange, true)

    expect(
      await screen.findByText('On — agents use the in-app browser until the extension connects.'),
    ).toBeVisible()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('shows mode-scoped lead ownership and selects another idle lead', () => {
    const onLeadChange = vi.fn()
    render(
      <WorkbenchBar
        activeAgent="EvoFlux"
        leadName="EvoFlux"
        leadOptions={[
          { name: 'EvoFlux', description: 'Default', model: null, is_default: true, members: [{ name: 'coder', description: null, model: null }] },
          { name: 'Research', description: 'Research lead', model: null, is_default: false, members: [{ name: 'explorer', description: null, model: null }] },
        ]}
        leadChanging={false}
        onLeadChange={onLeadChange}
        viewMode="agent"
        onViewModeChange={vi.fn()}
        onOpenMobileSidebar={vi.fn()}
        isMobile={false}
        isMacOverlay={false}
        mode="work"
        webBridgeEnabled={false}
        onWebBridgeEnabledChange={vi.fn()}
        webBridgePopoverOpen={false}
        onWebBridgePopoverOpenChange={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Select lead agent' }))
    expect(screen.getByText('coder')).toBeInTheDocument()
    expect(screen.getByText('explorer')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Research'))
    expect(onLeadChange).toHaveBeenCalledWith('Research')
  })

  it('uses the macOS title-bar navigation instead of rendering a duplicate mobile button', () => {
    const { container } = render(
      <WorkbenchBar
        activeAgent="Lead"
        leadName="Lead"
        leadOptions={[{ name: 'Lead', description: null, model: null, is_default: true, members: [] }]}
        leadChanging={false}
        onLeadChange={vi.fn()}
        viewMode="agent"
        onViewModeChange={vi.fn()}
        onOpenMobileSidebar={vi.fn()}
        isMobile
        isMacOverlay
        mode="work"
        webBridgeEnabled={false}
        onWebBridgeEnabledChange={vi.fn()}
        webBridgePopoverOpen={false}
        onWebBridgePopoverOpenChange={vi.fn()}
      />,
    )

    expect(screen.queryByRole('button', { name: 'Open navigation' })).not.toBeInTheDocument()
    const leadSelector = screen.getByRole('button', { name: 'Select lead agent' })
    expect(leadSelector).toHaveClass('w-8', 'sm:w-auto')
    expect(leadSelector.querySelector('[data-lead-icon]')).toHaveClass('lucide-users-round')
    expect(leadSelector.querySelector('span.hidden')).toHaveClass('sm:inline')
    expect(container.querySelector('header')).toHaveClass(
      'pl-(--spacing-mac-window-controls-inset)',
    )
  })

  it('uses the Windows title-bar sidebar toggle instead of rendering a duplicate mobile button', () => {
    const platform = vi.spyOn(navigator, 'platform', 'get').mockReturnValue('Win32')
    Object.defineProperty(window, '__TAURI_INTERNALS__', { configurable: true, value: {} })
    try {
      render(
        <WorkbenchBar
          activeAgent="Lead"
          leadName="Lead"
          leadOptions={[{ name: 'Lead', description: null, model: null, is_default: true, members: [] }]}
          leadChanging={false}
          onLeadChange={vi.fn()}
          viewMode="agent"
          onViewModeChange={vi.fn()}
          onOpenMobileSidebar={vi.fn()}
          isMobile
          isMacOverlay={false}
          mode="work"
          webBridgeEnabled={false}
          onWebBridgeEnabledChange={vi.fn()}
          webBridgePopoverOpen={false}
          onWebBridgePopoverOpenChange={vi.fn()}
        />,
      )

      expect(screen.queryByRole('button', { name: 'Open navigation' })).not.toBeInTheDocument()
    } finally {
      platform.mockRestore()
      delete (window as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__
    }
  })
})
