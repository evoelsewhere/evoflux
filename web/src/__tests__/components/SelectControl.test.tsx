import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { SelectControl } from '@/components/ui/select'

describe('SelectControl', () => {
  it('renders the shared themed popup and maps an empty option value', async () => {
    const onValueChange = vi.fn()
    render(
      <SelectControl
        ariaLabel="Evidence criterion"
        value="AC-1"
        onValueChange={onValueChange}
        options={[
          { value: '', label: 'Criterion…' },
          { value: 'AC-1', label: 'AC-1' },
        ]}
      />,
    )

    fireEvent.click(screen.getByRole('combobox', { name: 'Evidence criterion' }))
    const emptyOption = await screen.findByRole('option', { name: 'Criterion…' })
    expect(emptyOption.closest('[data-slot="select-content"]')).toBeInTheDocument()
    fireEvent.mouseMove(emptyOption)
    fireEvent.pointerDown(emptyOption, { pointerType: 'mouse' })
    fireEvent.mouseUp(emptyOption)
    fireEvent.click(emptyOption)

    await waitFor(() => expect(onValueChange).toHaveBeenCalledWith(''))
  })

  it('preserves the disabled state on the common trigger', () => {
    render(
      <SelectControl
        ariaLabel="Browser profile"
        value="shared"
        onValueChange={vi.fn()}
        disabled
        options={[{ value: 'shared', label: 'Shared' }]}
      />,
    )

    expect(screen.getByRole('combobox', { name: 'Browser profile' })).toBeDisabled()
  })
})
