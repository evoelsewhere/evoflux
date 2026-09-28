import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ToolCall } from '@/components/ToolCall'
import { useTeamStore } from '@/stores/useTeamStore'

const ARGS = JSON.stringify({ actions: [{ action: 'navigate', url: 'https://example.com' }] })

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
  useTeamStore.setState({ browserSession: null })
})

describe('See Browser on browser_use calls', () => {
  it('shows for a call the in-app browser ran', () => {
    render(
      <ToolCall name="browser_use" args={ARGS} done result="Navigated to https://example.com" />,
    )

    expect(screen.getByText('See Browser')).toBeInTheDocument()
  })

  it('hides for a call WebBridge ran in the user\'s browser', () => {
    render(
      <ToolCall
        name="browser_use"
        args={ARGS}
        done
        result={"Browser: the user's real Chrome/Edge through WebBridge (enabled and connected), not the in-app browser.\n---\nNavigated to https://example.com"}
      />,
    )

    expect(screen.queryByText('See Browser')).not.toBeInTheDocument()
  })

  it('waits for a live in-app session while the call is still running', () => {
    render(<ToolCall name="browser_use" args={ARGS} />)

    expect(screen.queryByText('See Browser')).not.toBeInTheDocument()
  })
})
