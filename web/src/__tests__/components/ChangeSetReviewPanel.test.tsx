import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type { ChangeSetResponse } from '@/api/types'
import { ChangeSetReviewPanel } from '@/components/ChangeSetReviewPanel'
import { useChangeSetStore } from '@/stores/useChangeSetStore'
import { useTeamStore } from '@/stores/useTeamStore'

const api = vi.hoisted(() => ({
  applyChangeSet: vi.fn(),
  rejectChangeSet: vi.fn(),
  runEditorAction: vi.fn(),
  codingWorkspaceFileUrl: vi.fn(() => '/file'),
  getChangeSetFileContent: vi.fn(),
}))

vi.mock('@/api/client', () => api)
vi.mock('@monaco-editor/react', () => ({
  DiffEditor: ({ original, modified }: { original: string; modified: string }) => (
    <div data-testid="monaco-diff">{original} → {modified}</div>
  ),
  loader: {
    __getMonacoInstance: () => null,
    init: () => Promise.resolve(null),
  },
}))

const proposal: ChangeSetResponse = {
  id: 'change-1',
  workspace: '/repo',
  origin: 'ai',
  title: 'Fix type mismatch',
  description: 'Review before apply',
  status: 'pending',
  snapshot_hash: null,
  verification_commands: ['uv run pytest --no-cov -q'],
  verification: [],
  created_at: 1,
  updated_at: 1,
  files: [
    {
      path: 'app/main.py',
      base_hash: 'a'.repeat(64),
      proposed_hash: 'b'.repeat(64),
      document_version: 3,
      diff: '--- a/app/main.py\n+++ b/app/main.py\n@@ -1 +1 @@\n-value = 1\n+value = 2',
      additions: 1,
      deletions: 1,
      status: 'pending',
    },
  ],
}

beforeEach(() => {
  api.applyChangeSet.mockReset()
  api.rejectChangeSet.mockReset()
  api.runEditorAction.mockReset()
  api.getChangeSetFileContent.mockReset()
  api.getChangeSetFileContent.mockResolvedValue({
    path: 'app/main.py',
    base_hash: 'a'.repeat(64),
    proposed_hash: 'b'.repeat(64),
    original_content: 'value = 1\n',
    proposed_content: 'value = 2\n',
    document_version: 3,
    status: 'pending',
  })
  useChangeSetStore.setState({ active: proposal, busy: false })
  useTeamStore.setState({ sessionId: 'session-1' })
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
})

describe('ChangeSetReviewPanel', () => {
  it('previews the guarded diff and accepts an individual file', async () => {
    const applied: ChangeSetResponse = {
      ...proposal,
      status: 'applied',
      files: [{ ...proposal.files[0]!, status: 'applied' }],
    }
    api.applyChangeSet.mockResolvedValue(applied)

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><ChangeSetReviewPanel /></QueryClientProvider>)

    expect(screen.getByText('Fix type mismatch')).toBeInTheDocument()
    expect(screen.getAllByText('app/main.py')).toHaveLength(2)
    expect(screen.getByText('+value = 2')).toBeInTheDocument()
    expect(screen.getByText('uv run pytest --no-cov -q')).toBeInTheDocument()
    expect(await screen.findByTestId('monaco-diff')).toHaveTextContent('value = 1')
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }))

    await waitFor(() => {
      expect(api.applyChangeSet).toHaveBeenCalledWith(
        '/repo',
        'change-1',
        ['app/main.py'],
        'session-1',
      )
    })
    expect(useChangeSetStore.getState().active?.files[0]?.status).toBe('applied')
  })

  it('rejects every pending file without applying it', async () => {
    api.rejectChangeSet.mockResolvedValue({
      ...proposal,
      status: 'rejected',
      files: [{ ...proposal.files[0]!, status: 'rejected' }],
    })

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><ChangeSetReviewPanel /></QueryClientProvider>)
    fireEvent.click(screen.getByRole('button', { name: 'Reject all' }))

    await waitFor(() => {
      expect(api.rejectChangeSet).toHaveBeenCalledWith('/repo', 'change-1', [
        'app/main.py',
      ])
    })
    expect(api.applyChangeSet).not.toHaveBeenCalled()
  })
})
