import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { WorkFolderSelector } from '@/components/WorkFolderSelector'
import { queryKeys } from '@/queries/keys'

const updateSessionWorkspace = vi.fn()

vi.mock('@/api/client', () => ({
  browseWorkspaces: vi.fn(),
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
