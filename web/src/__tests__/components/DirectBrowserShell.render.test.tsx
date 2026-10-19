import { act, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { DirectBrowserShell } from '@/components/BrowserViewer/DirectBrowserShell'

describe('DirectBrowserShell with the real tab hook', () => {
  it('mounts without a render loop', async () => {
    Object.defineProperty(window, '__TAURI_INTERNALS__', {
      configurable: true,
      value: {
        transformCallback: vi.fn(() => 0),
        invoke: vi.fn().mockResolvedValue(null),
      },
    })
    Object.defineProperty(window, '__TAURI_EVENT_PLUGIN_INTERNALS__', {
      configurable: true,
      value: { registerListener: vi.fn(), unregisterListener: vi.fn() },
    })
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
      }),
    })

    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })

    render(
      <DirectBrowserShell
        sessionId="session-render"
        workspace={null}
        tabId="panel-render"
        open
        visible
        onClose={() => {}}
      />,
    )
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50))
    })
    expect(screen.getByLabelText('Built-in browser')).toBeTruthy()
  })
})
