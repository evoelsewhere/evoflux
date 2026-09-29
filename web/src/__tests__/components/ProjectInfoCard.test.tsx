import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ProjectInfoCard } from '@/components/ProjectInfoCard'
import type { CodingProject } from '@/api/types'

const getCodingWorkspaceStatus = vi.fn()

vi.mock('@/api/client', () => ({
  getCodingWorkspaceStatus: (...args: unknown[]) => getCodingWorkspaceStatus(...args),
}))

vi.mock('@/lib/motion', () => ({
  useMotionPreset: () => ({}),
  fadeRise: () => ({ initial: false, animate: {}, transition: {} }),
}))

const project: CodingProject = {
  id: 'project-evo',
  name: 'Evo',
  description: null,
  kind: 'coding',
  settings: {},
  workspaces: [
    {
      workspace_id: 'repo-conductor',
      path: '/repos/evo-conductor',
      name: 'evo-conductor',
      display_name: null,
      sort_order: 0,
      kind: 'repository',
    },
    {
      workspace_id: 'repo-evoflux',
      path: '/repos/evoflux',
      name: 'evoflux',
      display_name: null,
      sort_order: 1,
      kind: 'repository',
    },
  ],
  created_at: '2026-08-21T00:00:00Z',
  updated_at: '2026-08-21T00:00:00Z',
}

describe('ProjectInfoCard', () => {
  beforeEach(() => {
    getCodingWorkspaceStatus.mockReset()
    getCodingWorkspaceStatus.mockResolvedValue({
      is_git_repo: true,
      branch: 'main',
      dirty: { staged: 0, unstaged: 0, untracked: 0 },
    })
  })

  it('matches the rich coding empty state and fills a project-aware suggestion', async () => {
    const onSuggestion = vi.fn()
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <ProjectInfoCard project={project} onSuggestion={onSuggestion} />
      </QueryClientProvider>,
    )

    expect(screen.getByRole('heading', { name: 'Evo' })).toBeInTheDocument()
    expect(screen.getByText('Shared coding context across 2 repositories.')).toBeInTheDocument()
    expect(screen.getByText('/repos/evo-conductor')).toBeInTheDocument()
    expect(screen.getByText('/repos/evoflux')).toBeInTheDocument()

    const suggestion = screen.getByRole('button', {
      name: 'Map how these repositories work together',
    })
    fireEvent.click(suggestion)

    expect(onSuggestion).toHaveBeenCalledWith('Map how these repositories work together')
    expect(await screen.findAllByText('main')).toHaveLength(2)
  })

  it('offers repository suggestions, not cross-repository ones, for a one-repo project', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const single: CodingProject = {
      ...project,
      name: 'evoflux',
      workspaces: [project.workspaces[1]!],
    }

    render(
      <QueryClientProvider client={queryClient}>
        <ProjectInfoCard project={single} />
      </QueryClientProvider>,
    )

    expect(screen.queryByText(/Shared coding context/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Explain this repository structure' })).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Find cross-repository integration risks' }),
    ).not.toBeInTheDocument()
    expect(await screen.findByText('main')).toBeInTheDocument()
  })
})
