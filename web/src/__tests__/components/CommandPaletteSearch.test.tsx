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

  fireEvent.change(screen.getByLabelText('Search everything'), {
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

  fireEvent.change(screen.getByLabelText('Search everything'), {
    target: { value: 'mở nơi quản lý sandbox' },
  })

  await waitFor(() => expect(screen.getByText('Sandbox Settings')).toBeInTheDocument())
})

it('groups asynchronous results and says so while they are in flight', async () => {
  let release: (items: unknown[]) => void = () => {}
  const search = vi.fn().mockImplementation(
    () => new Promise((resolve) => { release = resolve }),
  )
  render(
    <CommandPalette
      commands={[]}
      searchCommands={search as never}
      onClose={vi.fn()}
    />,
  )

  fireEvent.change(screen.getByLabelText('Search everything'), {
    target: { value: 'refund' },
  })

  // While the request is open the palette shows placeholder rows and says it
  // is working, rather than claiming nothing matches.
  await waitFor(() => expect(screen.getByTestId('palette-skeleton')).toBeInTheDocument())
  expect(screen.queryByText(/Nothing matches/)).not.toBeInTheDocument()
  expect(screen.getAllByText('Searching…').length).toBeGreaterThan(0)

  release([
    {
      id: 'app:session:7',
      group: 'Sessions',
      label: 'Refunds rewrite',
      description: 'work',
      action: vi.fn(),
    },
  ])

  await screen.findByText('Refunds rewrite')
  expect(screen.getByText('Sessions')).toBeInTheDocument()
  // Placeholders give way to the real rows once the results land.
  expect(screen.queryByTestId('palette-skeleton')).not.toBeInTheDocument()
})

it('reports a query that matched nothing anywhere', async () => {
  render(
    <CommandPalette
      commands={[]}
      searchCommands={vi.fn().mockResolvedValue([])}
      onClose={vi.fn()}
    />,
  )

  fireEvent.change(screen.getByLabelText('Search everything'), {
    target: { value: 'nowhere' },
  })

  await waitFor(() => expect(screen.getByText(/Nothing matches/)).toBeInTheDocument())
})
