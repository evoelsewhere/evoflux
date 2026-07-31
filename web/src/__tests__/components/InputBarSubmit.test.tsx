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
  vi.stubGlobal('ResizeObserver', class {
    observe = vi.fn()
    disconnect = vi.fn()
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

  it('accepts an arbitrary file and can submit it without typed text', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    const { container } = render(<InputBar onSubmit={onSubmit} />)
    const fileInput = container.querySelector<HTMLInputElement>('input[type="file"]')
    expect(fileInput).not.toBeNull()
    expect(fileInput).not.toHaveAttribute('accept')

    const file = new File([new Uint8Array([0, 1, 2])], 'archive.sqlite', {
      type: 'application/vnd.sqlite3',
    })
    fireEvent.change(fileInput!, { target: { files: [file] } })

    expect(screen.getByText('archive.sqlite')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(
        'Please inspect the attached file.',
        [file],
      )
    })
  })
})
