import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { Combobox } from '@/components/ui/combobox'

const items = [
  {
    value: '/repos/sqlite',
    label: 'sqlite',
    description: '/Users/example/Workspace/sqlite',
  },
  {
    value: '/repos/postgres',
    label: 'postgres',
    description: '/Users/example/Workspace/postgres',
  },
]

describe('Combobox', () => {
  it('filters rich options by label and path without exposing a clear action', async () => {
    render(
      <Combobox
        items={items}
        value="/repos/postgres"
        onValueChange={vi.fn()}
        ariaLabel="Select workspace"
        searchPlaceholder="Search workspaces or paths…"
        clearable={false}
      />,
    )

    fireEvent.click(screen.getByRole('combobox', { name: 'Select workspace' }))
    const search = await screen.findByRole('combobox', { name: 'Search Select workspace' })
    fireEvent.change(search, { target: { value: 'sqlite' } })

    await waitFor(() => {
      expect(screen.getByRole('option', { name: /sqlite/ })).toBeInTheDocument()
      expect(screen.queryByRole('option', { name: /postgres/ })).not.toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: 'Clear selection' })).not.toBeInTheDocument()
  })
})
