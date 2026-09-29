import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { OpenWithMenu } from '@/components/workbench/OpenWithMenu'

const mocks = vi.hoisted(() => ({ openWith: vi.fn() }))

vi.mock('@/api/tauri-workspace', () => ({ tauriOpenWorkspaceWith: mocks.openWith }))
vi.mock('@/queries/useWorkspaceOpenersQuery', () => ({
  useWorkspaceOpenersQuery: () => ({
    data: [{ id: 'vscode', name: 'VS Code', kind: 'editor' }],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
}))

beforeEach(() => {
  mocks.openWith.mockReset()
  mocks.openWith.mockResolvedValue(undefined)
})

describe('OpenWithMenu', () => {
  it('opens the primary repository by default', async () => {
    render(<OpenWithMenu workspace="/repos/api" repositories={['/repos/api', '/repos/web']} />)

    fireEvent.click(screen.getByRole('button', { name: 'Open workspace in a desktop app' }))
    fireEvent.click(await screen.findByText('VS Code'))

    await waitFor(() => expect(mocks.openWith).toHaveBeenCalledWith('/repos/api', 'vscode'))
  })

  it('opens the repository chosen in the menu', async () => {
    render(<OpenWithMenu workspace="/repos/api" repositories={['/repos/api', '/repos/web']} />)

    fireEvent.click(screen.getByRole('button', { name: 'Open workspace in a desktop app' }))
    fireEvent.click(await screen.findByRole('menuitemradio', { name: 'web' }))
    expect(await screen.findByText('Open web in')).toBeInTheDocument()
    fireEvent.click(screen.getByText('VS Code'))

    await waitFor(() => expect(mocks.openWith).toHaveBeenCalledWith('/repos/web', 'vscode'))
  })

  it('does not ask for a repository when there is only one', async () => {
    render(<OpenWithMenu workspace="/repos/api" repositories={['/repos/api']} />)

    fireEvent.click(screen.getByRole('button', { name: 'Open workspace in a desktop app' }))
    expect(await screen.findByText('Open workspace in')).toBeInTheDocument()
    expect(screen.queryByRole('menuitemradio')).not.toBeInTheDocument()
  })
})
