import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { RepositoryCodeReviews } from '@/api/types'
import { CreateReviewDialog } from '@/components/PullRequestsPanel'
import { useTeamStore } from '@/stores/useTeamStore'
import { useToastStore } from '@/stores/useToastStore'

const mocks = vi.hoisted(() => ({
  createReview: vi.fn(),
  runGitAIAction: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/client')>(),
  runGitAIAction: mocks.runGitAIAction,
}))

vi.mock('@/queries', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/queries')>(),
  useCreateCodeReviewMutation: () => ({
    isPending: false,
    mutateAsync: mocks.createReview,
  }),
}))

vi.mock('@/queries/useGitQuery', () => ({
  useGitRepositoryQuery: () => ({
    data: {
      is_git_repo: true,
      root: '/work/evoflux',
      branch: 'feature/review-draft',
      detached: false,
      upstream: 'origin/feature/review-draft',
      head_sha: 'abc123',
      head_subject: 'Improve review flow',
      user_name: 'Test User',
      user_email: 'test@example.com',
    },
  }),
  useGitBranchesQuery: () => ({
    data: [
      { name: 'main', current: false, remote: null, ahead: 0, behind: 0 },
      {
        name: 'feature/review-draft',
        current: true,
        remote: null,
        ahead: 1,
        behind: 0,
      },
      {
        name: 'origin/feature/review-draft',
        current: false,
        remote: 'origin',
        ahead: 0,
        behind: 0,
      },
    ],
  }),
  useGitRemotesQuery: () => ({
    data: [
      {
        name: 'origin',
        fetch_url: 'https://github.com/evoelsewhere/evoflux.git',
        push_url: 'https://github.com/evoelsewhere/evoflux.git',
      },
    ],
  }),
}))

const target: RepositoryCodeReviews = {
  workspace_id: 'workspace-1',
  project_id: 'project-1',
  workspace: '/work/evoflux',
  name: 'evoflux',
  remote_url: 'https://github.com/evoelsewhere/evoflux.git',
  repository: 'evoelsewhere/evoflux',
  detected_provider: 'github',
  suggested_domain: 'https://github.com',
  suggested_base_url: 'https://api.github.com',
  connection_id: 'connection-1',
  provider: 'github',
  items: [],
  error: null,
}

describe('Create review dialog AI draft', () => {
  beforeEach(() => {
    mocks.createReview.mockReset()
    mocks.runGitAIAction.mockReset()
    useTeamStore.setState({ sessionId: 'session-1' })
    useToastStore.setState({ toasts: [] })
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    })
  })

  it('fills the create form from the selected committed branch range', async () => {
    mocks.runGitAIAction.mockResolvedValue({
      kind: 'pr',
      summary: 'Review draft generated',
      title: 'Improve review workflow',
      body: '## Summary\n\nMoves AI actions into their relevant views.',
      message: null,
      findings: [],
      change_set: null,
      evidence_sha256: 'a'.repeat(64),
    })

    render(<CreateReviewDialog target={target} onClose={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Draft with AI' }))

    await waitFor(() => {
      expect(mocks.runGitAIAction).toHaveBeenCalledWith('/work/evoflux', {
        session_id: 'session-1',
        action: 'generate_pr_description',
        remote_context: {
          source_branch: 'feature/review-draft',
          target_branch: 'main',
        },
      })
    })
    expect(screen.getByDisplayValue('Improve review workflow')).toBeVisible()
    expect(screen.getByPlaceholderText('Summary, validation, and rollout notes…')).toHaveValue(
      '## Summary\n\nMoves AI actions into their relevant views.',
    )
  })

  it('explains the task requirement instead of rendering an inert control', () => {
    useTeamStore.setState({ sessionId: null })

    render(<CreateReviewDialog target={target} onClose={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Draft with AI' }))

    expect(mocks.runGitAIAction).not.toHaveBeenCalled()
    expect(useToastStore.getState().toasts.at(-1)?.title).toBe(
      'Open a coding task to draft with AI',
    )
  })
})
