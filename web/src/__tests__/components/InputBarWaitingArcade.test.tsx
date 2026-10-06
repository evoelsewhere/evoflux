import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { InputBar } from '@/components/InputBar'

describe('InputBar waiting arcade slot', () => {
  beforeEach(() => {
    window.matchMedia = vi.fn().mockImplementation((media: string) => ({
      matches: false,
      media,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))
  })

  it('shows the optional working action beside Stop without moving focus on render', () => {
    const { rerender } = render(<InputBar onSubmit={() => undefined} onStop={() => undefined} isStreaming />)
    const composer = screen.getByRole('textbox')
    composer.focus()
    expect(document.activeElement).toBe(composer)
    expect(screen.queryByRole('button', { name: 'Play while waiting' })).not.toBeInTheDocument()

    rerender(
      <InputBar
        onSubmit={() => undefined}
        onStop={() => undefined}
        isStreaming
        workingActionSlot={<button type="button" aria-label="Play while waiting">Arcade</button>}
      />,
    )

    const arcade = screen.getByRole('button', { name: 'Play while waiting' })
    const stop = screen.getByRole('button', { name: 'Stop generation' })
    expect(arcade).toBeInTheDocument()
    expect(arcade.compareDocumentPosition(stop) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(document.activeElement).toBe(composer)
  })

  it('does not render the working action while idle', () => {
    render(
      <InputBar
        onSubmit={() => undefined}
        workingActionSlot={<button type="button" aria-label="Play while waiting">Arcade</button>}
      />,
    )
    expect(screen.queryByRole('button', { name: 'Play while waiting' })).not.toBeInTheDocument()
  })
})
