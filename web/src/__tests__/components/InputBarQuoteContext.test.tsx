import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createRef } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { InputBar, type InputBarHandle } from '@/components/InputBar'

describe('InputBar selected-chat context', () => {
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

  it('shows selected text as a context card without exposing markdown syntax', async () => {
    const ref = createRef<InputBarHandle>()
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(<InputBar ref={ref} onSubmit={onSubmit} />)

    act(() => {
      ref.current?.setQuoteContext('Quy định lao động quan trọng')
    })

    expect(screen.getByText('Selected from chat')).toBeInTheDocument()
    expect(screen.getByText('Quy định lao động quan trọng')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Message input' })).toHaveValue('')

    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(
        '> Quy định lao động quan trọng',
        undefined,
      )
    })
  })

  it('lets the user remove selected context without changing the draft', () => {
    const ref = createRef<InputBarHandle>()
    render(<InputBar ref={ref} onSubmit={vi.fn()} />)

    act(() => {
      ref.current?.setQuoteContext('Context to remove')
      ref.current?.appendValue('Keep this question')
    })
    fireEvent.click(
      screen.getByRole('button', { name: 'Remove selected chat context' }),
    )

    expect(screen.queryByText('Selected from chat')).not.toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Message input' })).toHaveValue(
      'Keep this question',
    )
  })
})
