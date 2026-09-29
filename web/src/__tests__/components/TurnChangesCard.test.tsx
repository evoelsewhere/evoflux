import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { TurnChangesCard } from '@/components/TurnChangesCard'
import type { CodingProject, TurnChangesPending } from '@/api/types'
import { queryKeys } from '@/queries/keys'
import { useTeamStore } from '@/stores/useTeamStore'
import { useUIStore } from '@/stores/useUIStore'

function renderWithQueries(ui: ReactElement, queryClient = new QueryClient()) {
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

const changes: TurnChangesPending = {
  sessionId: 'session-1',
  additions: 503,
  deletions: 23,
  files: [
    { path: 'desktop/src-tauri/src/main.rs', status: 'modified', additions: 1, deletions: 1 },
    { path: 'web/public/appearance-init.js', status: 'modified', additions: 2, deletions: 2 },
    { path: 'web/src/components/SettingsScreen.tsx', status: 'modified', additions: 4, deletions: 1 },
    { path: 'web/src/components/TurnChangesCard.tsx', status: 'added', additions: 180, deletions: 0 },
  ],
}

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

describe('TurnChangesCard', () => {
  it('shows totals and expands the remaining file list', () => {
    renderWithQueries(<TurnChangesCard changes={changes} />)

    expect(screen.getByText('Edited 4 files')).toBeInTheDocument()
    expect(screen.getByText('+503')).toBeInTheDocument()
    expect(screen.getByText('−23')).toBeInTheDocument()
    expect(screen.getByText('desktop/src-tauri/src/main.rs')).toBeInTheDocument()
    expect(screen.queryByText('web/src/components/TurnChangesCard.tsx')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Show 1 more files' }))

    expect(screen.getByText('web/src/components/TurnChangesCard.tsx')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show fewer files' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
  })

  it('reviews a change in the repository of the project that owns it', () => {
    const project: CodingProject = {
      id: 'project-1',
      name: 'MR',
      description: null,
      kind: 'coding',
      settings: {},
      workspaces: [
        { workspace_id: 'a', path: '/repos/api', name: 'api', display_name: null, sort_order: 0, kind: 'repo' },
        { workspace_id: 'w', path: '/repos/web', name: 'web', display_name: null, sort_order: 1, kind: 'repo' },
      ],
      created_at: '',
      updated_at: '',
    }
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    queryClient.setQueryData(queryKeys.projects.detail('project-1'), project)
    queryClient.setQueryData(queryKeys.codingOverview(), { projects: [project], repositories: [] })
    useTeamStore.setState({ _workspace: '/repos/api', projectId: 'project-1' })
    const openGitChanges = vi.fn()
    useUIStore.setState({ openGitChanges })

    renderWithQueries(
      <TurnChangesCard
        changes={{
          sessionId: 'session-1',
          additions: 1,
          deletions: 0,
          files: [{ path: '../web/src/users.ts', status: 'modified', additions: 1, deletions: 0 }],
        }}
      />,
      queryClient,
    )
    fireEvent.click(screen.getByTitle('Review ../web/src/users.ts'))

    expect(openGitChanges).toHaveBeenCalledWith('/repos/web')
  })
})
