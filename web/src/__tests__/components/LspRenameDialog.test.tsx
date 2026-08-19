import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { LspRenameDialog } from '@/components/LspRenameDialog'

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

describe('LspRenameDialog', () => {
  it('collects the new name in an in-app dialog', async () => {
    const rename = vi.fn().mockResolvedValue(undefined)
    const close = vi.fn()
    render(
      <LspRenameDialog
        request={{ currentName: 'oldName', line: 4, column: 7 }}
        onClose={close}
        onRename={rename}
      />,
    )

    const input = screen.getByLabelText('New name')
    expect(input).toHaveValue('oldName')
    fireEvent.change(input, { target: { value: 'newName' } })
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }))

    await waitFor(() => expect(rename).toHaveBeenCalledWith('newName'))
    expect(close).toHaveBeenCalled()
  })

  it('keeps the dialog open and shows an LSP failure', async () => {
    const rename = vi.fn().mockRejectedValue(new Error('Rename is unavailable'))
    const close = vi.fn()
    render(
      <LspRenameDialog
        request={{ currentName: 'oldName', line: 4, column: 7 }}
        onClose={close}
        onRename={rename}
      />,
    )

    fireEvent.change(screen.getByLabelText('New name'), {
      target: { value: 'newName' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Rename is unavailable')
    expect(close).not.toHaveBeenCalled()
  })
})
