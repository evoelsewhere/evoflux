import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Thinking } from '@/components/Thinking'

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

describe('Thinking', () => {
  it('opens during streaming and collapses when streaming finishes', async () => {
    const { rerender } = render(
      <Thinking content="Inspecting the request" isStreaming />,
    )
    const trigger = screen.getByRole('button', { name: /collapse thinking/i })

    expect(trigger).toHaveAttribute('aria-expanded', 'true')

    rerender(<Thinking content="Inspecting the request" isStreaming={false} />)

    await waitFor(() => {
      expect(trigger).toHaveAttribute('aria-expanded', 'false')
    })
  })

  it('starts collapsed when the trace is already complete', () => {
    render(<Thinking content="Completed reasoning" isStreaming={false} />)
    const trigger = screen.getByRole('button', { name: /expand thought/i })

    expect(trigger).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(trigger)

    expect(trigger).toHaveAttribute('aria-expanded', 'true')
  })
})
