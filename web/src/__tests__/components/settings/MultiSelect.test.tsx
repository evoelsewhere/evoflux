import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { MultiSelect } from '@/components/settings/MultiSelect'

describe('MultiSelect', () => {
  it('keeps managed selections fully inert when disabled', () => {
    const onChange = vi.fn()
    render(
      <MultiSelect
        ariaLabel="Managed tools"
        disabled
        options={[{ value: 'browser', label: 'Browser' }]}
        value={['browser']}
        onChange={onChange}
      />,
    )

    const trigger = screen.getByRole('combobox', { name: 'Managed tools' })
    expect(trigger).toHaveAttribute('aria-disabled', 'true')
    expect(trigger).toHaveAttribute('tabindex', '-1')

    fireEvent.click(trigger)
    fireEvent.click(screen.getByRole('button', { name: 'Remove browser' }))

    expect(screen.queryByPlaceholderText('Search…')).not.toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()
  })
})
