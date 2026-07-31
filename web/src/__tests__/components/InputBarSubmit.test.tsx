import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
})

describe('InputBar submit lifecycle', () => {
  it('clears the visible draft before an accepted request finishes', async () => {
    let accept!: () => void
    const onSubmit = vi.fn(
      () => new Promise<void>((resolve) => {
        accept = resolve
      }),
    )
    render(<InputBar onSubmit={onSubmit} />)

    const input = screen.getByRole('textbox', { name: 'Message input' })
    fireEvent.change(input, { target: { value: 'Ship this change' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    expect(input).toHaveValue('')
    expect(onSubmit).toHaveBeenCalledWith('Ship this change', undefined)

    await act(async () => {
      accept()
    })
  })

  it('restores the draft when the parent rejects the send', async () => {
    const onSubmit = vi.fn().mockResolvedValue(false)
    render(<InputBar onSubmit={onSubmit} />)

    const input = screen.getByRole('textbox', { name: 'Message input' })
    fireEvent.change(input, { target: { value: 'Keep this draft' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    await waitFor(() => {
      expect(input).toHaveValue('Keep this draft')
    })
  })
})
