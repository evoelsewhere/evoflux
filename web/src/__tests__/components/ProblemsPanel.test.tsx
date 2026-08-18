import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChangeSetResponse, ProblemsResponse } from '@/api/types'
import { ProblemsPanel } from '@/components/ProblemsPanel'
import { useChangeSetStore } from '@/stores/useChangeSetStore'

const mocks = vi.hoisted(() => ({
  createChangeSet: vi.fn(),
  mutate: vi.fn(),
  refetch: vi.fn(),
}))

const problems: ProblemsResponse = {
  counts: { error: 1, warning: 1, info: 0, hint: 0, total: 2 },
  problems: [
    {
      id: 'lsp-1',
      workspace: '/repo',
      source: 'lsp',
      scope: 'lsp:app.py',
      message: 'Argument has the wrong type',
      severity: 'error',
      path: 'app.py',
      line: 4,
      column: 2,
      end_line: 4,
      end_column: 8,
      code: 'reportArgumentType',
      title: null,
      details: null,
      fix: { workspace_edit: { changes: {} } },
      suppression_key: 'lsp:reportArgumentType',
      provenance: { producer: 'pyright' },
      session_id: 'session-1',
      status: 'open',
      created_at: 1,
      updated_at: 1,
    },
    {
      id: 'plugin-1',
      workspace: '/repo',
      source: 'plugin',
      scope: 'plugin:one',
      message: 'Manifest is invalid',
      severity: 'warning',
      path: null,
      line: null,
      column: null,
      end_line: null,
      end_column: null,
      code: 'invalid-manifest',
      title: 'Plugin manifest',
      details: null,
      fix: null,
      suppression_key: 'plugin:invalid-manifest',
      provenance: {},
      session_id: null,
      status: 'open',
      created_at: 1,
      updated_at: 1,
    },
  ],
}

vi.mock('@/api/client', () => ({ createChangeSet: mocks.createChangeSet }))
vi.mock('@/queries', () => ({
  useProblemsQuery: () => ({
    data: problems,
    isLoading: false,
    isFetching: false,
    refetch: mocks.refetch,
  }),
  useProblemDecisionMutation: () => ({ mutate: mocks.mutate }),
}))

beforeEach(() => {
  mocks.createChangeSet.mockReset()
  mocks.mutate.mockReset()
  mocks.refetch.mockReset()
  useChangeSetStore.setState({ active: null, busy: false })
})

describe('ProblemsPanel', () => {
  it('unifies sources and exposes finding actions', () => {
    const send = vi.fn()
    render(<ProblemsPanel workspace="/repo" active onSendToAgent={send} />)

    expect(screen.getByText('1 errors · 1 warnings')).toBeInTheDocument()
    expect(screen.getByText('Argument has the wrong type')).toBeInTheDocument()
    expect(screen.getByText('Plugin manifest')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: 'Dismiss' })[0]!)
    expect(mocks.mutate).toHaveBeenCalledWith({ id: 'lsp-1', action: 'dismiss' })
    fireEvent.click(screen.getAllByRole('button', { name: /Send to agent/ })[0]!)
    expect(send).toHaveBeenCalledWith(expect.stringContaining('Investigate and fix'))
  })

  it('stages a structured fix as a guarded ChangeSet', async () => {
    const staged = {
      id: 'change-1',
      workspace: '/repo',
      origin: 'lsp',
      title: 'Fix type mismatch',
      description: null,
      status: 'pending',
      snapshot_hash: null,
      created_at: 1,
      updated_at: 1,
      files: [],
    } satisfies ChangeSetResponse
    mocks.createChangeSet.mockResolvedValue(staged)
    render(<ProblemsPanel workspace="/repo" active />)

    fireEvent.click(screen.getByRole('button', { name: 'Fix' }))

    await waitFor(() => expect(mocks.createChangeSet).toHaveBeenCalled())
    expect(useChangeSetStore.getState().active?.id).toBe('change-1')
  })
})
