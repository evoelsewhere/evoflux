import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'

import { CommandPalette } from '@/components/CommandPalette'

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
  Element.prototype.scrollIntoView = vi.fn()
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
})

it('merges asynchronous repository results with local actions', async () => {
  const open = vi.fn()
  const search = vi.fn().mockResolvedValue([
    {
      id: 'search:file:auth.py',
      group: 'Files',
      label: 'app/auth.py',
      description: 'Repository file',
      action: open,
    },
  ])
  render(
    <CommandPalette
      commands={[]}
      searchCommands={search}
      onClose={vi.fn()}
    />,
  )

  fireEvent.change(screen.getByLabelText('Search commands'), {
    target: { value: 'auth' },
  })

  await screen.findByText('app/auth.py')
  expect(search).toHaveBeenCalledWith('auth', expect.any(AbortSignal))
  fireEvent.click(screen.getByText('app/auth.py'))
  expect(open).toHaveBeenCalled()
})

it('routes a natural-language phrase through command keywords', async () => {
  render(
    <CommandPalette
      commands={[
        {
          id: 'sandbox',
          label: 'Sandbox Settings',
          description: 'Policies',
          keywords: ['mở nơi quản lý sandbox'],
          action: vi.fn(),
        },
      ]}
      onClose={vi.fn()}
    />,
  )

  fireEvent.change(screen.getByLabelText('Search commands'), {
    target: { value: 'mở nơi quản lý sandbox' },
  })

  await waitFor(() => expect(screen.getByText('Sandbox Settings')).toBeInTheDocument())
})
