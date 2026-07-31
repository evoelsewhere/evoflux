import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { InputBar } from '@/components/InputBar'

describe('InputBar WebBridge control', () => {
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

  it('renders with the session controls and toggles web access', () => {
    const onWebBridgeEnabledChange = vi.fn()
    render(
      <InputBar
        onSubmit={vi.fn()}
        webBridgeEnabled={false}
        onWebBridgeEnabledChange={onWebBridgeEnabledChange}
        permissionMode="auto"
        onPermissionModeChange={vi.fn()}
      />,
    )

    const webControl = screen.getByRole('button', { name: 'Enable WebBridge' })
    const permissionControl = screen.getByRole('button', { name: 'Auto mode' })

    expect(webControl).toHaveTextContent('Web')
    expect(
      webControl.compareDocumentPosition(permissionControl)
      & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()

    fireEvent.click(webControl)
    expect(onWebBridgeEnabledChange).toHaveBeenCalledWith(true)
  })

  it('makes the enabled state explicit', () => {
    render(
      <InputBar
        onSubmit={vi.fn()}
        webBridgeEnabled
        onWebBridgeEnabledChange={vi.fn()}
      />,
    )

    const webControl = screen.getByRole('button', { name: 'Disable WebBridge' })
    expect(webControl).toHaveAttribute('aria-pressed', 'true')
    expect(webControl).toHaveTextContent('Web on')
  })
})
