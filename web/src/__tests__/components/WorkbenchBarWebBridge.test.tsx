import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  ) {
    render(
      <WorkbenchBar
        identity="Lead"
        activeAgent="Lead"
        agentNames={['Lead']}
        viewMode="agent"
        onViewModeChange={vi.fn()}
        onSelectAgent={vi.fn()}
        onOpenMobileSidebar={vi.fn()}
        isMobile={false}
        isMacOverlay={false}
        webBridgeEnabled={enabled}
        onWebBridgeEnabledChange={onChange}
        webBridgePopoverOpen={popoverOpen}
        onWebBridgePopoverOpenChange={onPopoverOpenChange}
      />,
    )
    return { onChange, onPopoverOpenChange }
  }

  it('opens WebBridge settings from the top bar without enabling it immediately', () => {
    const { onChange, onPopoverOpenChange } = renderBar(false)
    const control = screen.getByRole('button', { name: 'Open WebBridge' })

    expect(control).toHaveTextContent('WebBridge')

    fireEvent.click(control)
    expect(onPopoverOpenChange.mock.calls[0]?.[0]).toBe(true)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('enables WebBridge explicitly when the extension is connected', async () => {
    const onChange = vi.fn()
    renderBar(false, onChange, true)
    const enableButton = screen.getByRole('button', { name: 'Enable WebBridge for this chat' })

    await waitFor(() => expect(enableButton).toBeEnabled())
    fireEvent.click(enableButton)
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it('blocks enable while the extension is disconnected', async () => {
    webBridgeApi.getWebBridgeStatus.mockResolvedValue({ connected: false, extensions: [] })
    const onChange = vi.fn()
    renderBar(false, onChange, true)
    const enableButton = screen.getByRole('button', { name: 'Enable WebBridge for this chat' })

    await waitFor(() => expect(enableButton).toBeDisabled())
    fireEvent.click(enableButton)
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByText('Connect the browser extension to enable WebBridge.')).toBeVisible()
  })

  it('turns off an enabled chat when the extension disconnects', async () => {
    webBridgeApi.getWebBridgeStatus.mockResolvedValue({ connected: false, extensions: [] })
    const onChange = vi.fn()
    renderBar(true, onChange, true)

    await waitFor(() => expect(onChange).toHaveBeenCalledWith(false))
  })
})
