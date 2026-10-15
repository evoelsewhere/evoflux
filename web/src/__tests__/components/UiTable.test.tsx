import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { UiTable } from '@/components/ui/UiTable'
import type { UiTableBlock } from '@/components/ui/ui-block-types'

describe('UiTable', () => {
  const rows = Array.from({ length: 10 }, (_, index) => ({
    name: `Item ${10 - index}`,
    price: (10 - index) * 10,
  }))
  const block: UiTableBlock = {
    type: 'table' as const,
    columns: [{ name: 'Name' }, { price: 'Price' }] as Record<string, string>[],
    rows,
  }

  it('sorts numeric columns and filters rows without changing the source data', () => {
    render(<UiTable block={block} />)
    const table = screen.getByRole('table')

    fireEvent.click(within(table).getByRole('button', { name: 'Price' }))
    expect(within(table).getAllByRole('row')[1]).toHaveTextContent('Item 1')
    expect(within(table).getByRole('columnheader', { name: /Price/ }))
      .toHaveAttribute('aria-sort', 'ascending')

    fireEvent.change(screen.getByRole('textbox', { name: 'Filter table rows' }), {
      target: { value: 'Item 10' },
    })
    expect(within(table).getAllByRole('row')).toHaveLength(2)
    expect(within(table).getByText('Item 10')).toBeInTheDocument()
    expect(block.rows).toHaveLength(10)
  })
})
