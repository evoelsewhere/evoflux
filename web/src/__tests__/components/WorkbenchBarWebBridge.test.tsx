import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { WorkbenchBar } from '@/components/workbench/WorkbenchBar'

vi.mock('@/queries', () => ({
  useRegistryQuery: () => ({ data: undefined }),
}))

describe('WorkbenchBar browser access control', () => {
  beforeEach(() => {
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

  it('enables WebBridge explicitly from the anchored popover', () => {
    const onChange = vi.fn()
    renderBar(false, onChange, true)
    const enableButton = screen.getByRole('button', { name: 'Enable WebBridge for this chat' })

    fireEvent.click(enableButton)
    expect(onChange).toHaveBeenCalledWith(true)
  })
})
