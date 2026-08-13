import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { WorkFolderSelector } from '@/components/WorkFolderSelector'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { queryKeys } from '@/queries/keys'

const updateSessionWorkspace = vi.fn()
const listTeamSessions = vi.fn()

vi.mock('@/api/client', () => ({
  browseWorkspaces: vi.fn(),
  listTeamSessions: (...args: unknown[]) => listTeamSessions(...args),
  updateSessionWorkspace: (...args: unknown[]) => updateSessionWorkspace(...args),
}))

vi.mock('@/hooks/use-platform', () => ({
  usePlatform: () => ({ isTauri: false, os: 'unknown', isMacOverlay: false }),
}))

function renderSelector(
  queryClient: QueryClient,
  props: React.ComponentProps<typeof WorkFolderSelector>,
) {
  return render(
    <QueryClientProvider client={queryClient}>
      <WorkFolderSelector {...props} />
    </QueryClientProvider>,
  )
}

describe('WorkFolderSelector', () => {
  beforeEach(() => {
    updateSessionWorkspace.mockReset()
    listTeamSessions.mockReset()
    listTeamSessions.mockResolvedValue({ data: [], next_cursor: null, has_more: false })
    localStorage.clear()
  })

  it('shows recent folders from persisted choices and Work sessions', async () => {
    localStorage.setItem(
      STORAGE_KEYS.work.recentWorkspaceFolders,
      JSON.stringify(['/Users/me/persisted-project']),
    )
    listTeamSessions.mockResolvedValue({
      data: [
        { id: 'recent-session', mode: 'work', workspace: '/Users/me/session-project' },
      ],
      next_cursor: null,
      has_more: false,
    })
    const queryClient = new QueryClient()
    updateSessionWorkspace.mockResolvedValue({
      session_id: 'session-123',
      workspace_root: '/Users/me/session-project',
      files: [],
      truncated: false,
    })
    renderSelector(queryClient, {
      sessionId: 'session-123',
      workspaceRoot: '/tmp/evoflux/session-123',
    })

    fireEvent.click(screen.getByRole('button', { name: 'Work folder: Session folder' }))

    expect(await screen.findByText('Recent folders')).toBeInTheDocument()
    expect(screen.getByText('persisted-project')).toBeInTheDocument()
    fireEvent.click(await screen.findByText('session-project'))

    await waitFor(() => {
      expect(updateSessionWorkspace).toHaveBeenCalledWith(
        'session-123',
        '/Users/me/session-project',
      )
    })
  })

  it('shows the private session folder as the default', () => {
    const queryClient = new QueryClient()
    renderSelector(queryClient, {
      sessionId: 'session-123',
      workspaceRoot: '/tmp/evoflux/session-123',
    })

    const trigger = screen.getByRole('button', { name: 'Work folder: Session folder' })
    expect(trigger).toHaveTextContent('Session folder')
    expect(trigger).toHaveTextContent('Default')
  })

  it('resets a custom folder and clears stale composer references', async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(queryKeys.fileRefs.session('session-123'), [{ path: 'old.txt' }])
    updateSessionWorkspace.mockResolvedValue({
      session_id: 'session-123',
      workspace_root: '/tmp/evoflux/session-123',
      files: [],
      truncated: false,
    })

    renderSelector(queryClient, {
      sessionId: 'session-123',
      workspaceRoot: '/Users/me/project',
    })

    fireEvent.click(screen.getByRole('button', { name: 'Work folder: project' }))
    fireEvent.click(await screen.findByText('Session folder', { selector: 'span.block' }))

    await waitFor(() => {
      expect(updateSessionWorkspace).toHaveBeenCalledWith('session-123', null)
    })
    expect(queryClient.getQueryData(queryKeys.team.workspaceRoot('session-123'))).toEqual({
      session_id: 'session-123',
      workspace_root: '/tmp/evoflux/session-123',
    })
    expect(queryClient.getQueryData(queryKeys.fileRefs.session('session-123'))).toBeUndefined()
  })
})
