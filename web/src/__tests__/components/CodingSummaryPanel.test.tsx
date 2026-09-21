/**
 * The Overview panel describes a repository, and a Coding project has several.
 *
 * It used to describe the one the session opened on — the project's first, by
 * insertion order — as though it were the project: one branch, one set of
 * changes, one set of pull requests, and nothing saying the others existed.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { CodingSummaryPanel } from '@/components/CodingSummaryPanel'

const mocks = vi.hoisted(() => ({
  gitChanges: vi.fn(),
  gitArgs: vi.fn(),
  todos: vi.fn(),
}))

vi.mock('@/queries/useGitQuery', () => ({
  useGitChangesQuery: (workspace: string, open: boolean) => {
    mocks.gitArgs(workspace, open)
    return mocks.gitChanges()
  },
}))

vi.mock('@/queries/useTodosQuery', () => ({
  useTodosQuery: () => mocks.todos(),
}))

function gitState(branch: string) {
  return {
    data: {
      is_git_repo: true,
      branch,
      files: [],
      ahead: 0,
      behind: 0,
    },
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  }
}

const REPOSITORIES = [
  { path: '/work/agent-desktop', label: 'agent-desktop' },
  { path: '/work/evo-computer-use', label: 'evo-computer-use' },
]

beforeEach(() => {
  mocks.gitChanges.mockReturnValue(gitState('main'))
  mocks.todos.mockReturnValue({ data: { todos: [] }, isFetching: false, refetch: vi.fn() })
})

function panel(props: Partial<Parameters<typeof CodingSummaryPanel>[0]> = {}) {
  return render(
    <CodingSummaryPanel
      workspace="/work/agent-desktop"
      sessionId="session-1"
      open
      isWorking={false}
      {...props}
    />,
  )
}

describe('Overview panel across a project', () => {
  it('offers every repository in the project', () => {
    panel({ repositories: REPOSITORIES })

    expect(screen.getByRole('tab', { name: 'agent-desktop' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'evo-computer-use' })).toBeInTheDocument()
  })

  it('starts on the repository the session opened in', () => {
    panel({ repositories: REPOSITORIES })

    expect(screen.getByRole('tab', { name: 'agent-desktop' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(mocks.gitArgs).toHaveBeenLastCalledWith('/work/agent-desktop', true)
  })

  it('reads the repository the reader picked', () => {
    panel({ repositories: REPOSITORIES })

    fireEvent.click(screen.getByRole('tab', { name: 'evo-computer-use' }))

    expect(mocks.gitArgs).toHaveBeenLastCalledWith('/work/evo-computer-use', true)
    // The header names it too, not just the tab.
    expect(screen.getByText('/work/evo-computer-use')).toBeInTheDocument()
  })

  it('shows no switcher for a standalone repository', () => {
    panel()

    expect(screen.queryByRole('tablist', { name: 'Project repository' })).not.toBeInTheDocument()
  })
})
