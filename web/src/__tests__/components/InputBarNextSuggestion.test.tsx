import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { InputBar } from '@/components/InputBar'

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

const SUGGESTION = { message: 'Run the test suite', reason: 'Natural next step' }

describe('InputBar next-message ghost text', () => {
  it('shows the suggestion as ghost text while the composer is empty and idle', () => {
    render(<InputBar onSubmit={vi.fn()} suggestion={SUGGESTION} />)

    const input = screen.getByRole('textbox', { name: 'Message input' })
    expect(input).toHaveValue('')
    // The placeholder steps aside while the ghost text is up.
    expect(input).toHaveAttribute('placeholder', '')
    expect(screen.getByText('Run the test suite')).toBeVisible()
    expect(screen.getByText('Tab')).toBeVisible()
  })

  it('accepts the suggestion on Tab and leaves the caret at the end', async () => {
    render(<InputBar onSubmit={vi.fn()} suggestion={SUGGESTION} />)

    const input = screen.getByRole('textbox', { name: 'Message input' }) as HTMLTextAreaElement
    fireEvent.keyDown(input, { key: 'Tab' })

    expect(input).toHaveValue('Run the test suite')
    await waitFor(() => {
      expect(input.selectionStart).toBe('Run the test suite'.length)
      expect(input.selectionEnd).toBe('Run the test suite'.length)
    })
    // The ghost layer is gone (the mirror overlay and the textarea itself
    // still show the accepted text, so target the ghost's role explicitly).
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('hides the ghost while typing and brings it back when the input is emptied', () => {
    render(<InputBar onSubmit={vi.fn()} suggestion={SUGGESTION} />)
    const input = screen.getByRole('textbox', { name: 'Message input' })

    fireEvent.change(input, { target: { value: 'n' } })
    expect(screen.queryByText('Run the test suite')).not.toBeInTheDocument()

    fireEvent.change(input, { target: { value: '' } })
    expect(screen.getByText('Run the test suite')).toBeVisible()
  })

  it('dismisses the suggestion on Escape', () => {
    const onSuggestionDismiss = vi.fn()
    render(
      <InputBar
        onSubmit={vi.fn()}
        suggestion={SUGGESTION}
        onSuggestionDismiss={onSuggestionDismiss}
      />,
    )

    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Message input' }), { key: 'Escape' })

    expect(onSuggestionDismiss).toHaveBeenCalledTimes(1)
  })

  it('ignores Tab during IME composition', () => {
    const onSubmit = vi.fn()
    render(<InputBar onSubmit={onSubmit} suggestion={SUGGESTION} />)
    const input = screen.getByRole('textbox', { name: 'Message input' })

    fireEvent.compositionStart(input)
    fireEvent.keyDown(input, { key: 'Tab' })
    fireEvent.compositionEnd(input)
    // Legacy composition signalling arrives as keyCode 229 instead.
    fireEvent.keyDown(input, { key: 'Tab', keyCode: 229 })

    expect(input).toHaveValue('')
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByText('Run the test suite')).toBeVisible()
  })

  it('keeps the streaming Tab lane working while a suggestion is present', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(
      <InputBar onSubmit={onSubmit} isStreaming followUpLane="queue" suggestion={SUGGESTION} />,
    )
    const input = screen.getByRole('textbox', { name: 'Message input' })
    fireEvent.change(input, { target: { value: 'one more pass' } })

    fireEvent.keyDown(input, { key: 'Tab' })

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith('one more pass', undefined, 'steer')
    })
  })
})
