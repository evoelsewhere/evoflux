import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChangeSetResponse, EditorActionRequest } from '@/api/types'
import { EditorAiActionDialog } from '@/components/EditorAiActionDialog'
import { useChangeSetStore } from '@/stores/useChangeSetStore'

const api = vi.hoisted(() => ({
  previewEditorContext: vi.fn(),
  runEditorAction: vi.fn(),
}))

vi.mock('@/api/client', () => api)

const request: EditorActionRequest = {
  session_id: 'session-1',
  action: 'refactor_selection',
  active_file: 'app.py',
  content: 'value = 1\n',
  document_version: 3,
  selection: {
    text: 'value = 1',
    start_line: 1,
    start_column: 1,
    end_line: 1,
    end_column: 10,
  },
  diagnostics: [],
}

beforeEach(() => {
  api.previewEditorContext.mockReset()
  api.runEditorAction.mockReset()
  api.previewEditorContext.mockResolvedValue({
    context_sha256: 'c'.repeat(64),
    context: {
      active_file: 'app.py',
      provenance: [
        { kind: 'active_file', source: 'editor-buffer', path: 'app.py' },
      ],
    },
  })
  useChangeSetStore.setState({ active: null, busy: false })
})

describe('EditorAiActionDialog', () => {
  it('previews exact context without invoking the model', async () => {
    render(
      <EditorAiActionDialog
        workspace="/repo"
        request={request}
        onClose={vi.fn()}
      />,
    )

    await screen.findByText('active_file · editor-buffer')
    expect(api.previewEditorContext).toHaveBeenCalledWith(
      '/repo',
      { ...request, mention_paths: [] },
      expect.any(AbortSignal),
    )
    expect(api.runEditorAction).not.toHaveBeenCalled()
  })

  it('runs only after confirmation and opens the guarded ChangeSet', async () => {
    const changeSet = {
      id: 'change-1',
      workspace: '/repo',
      origin: 'ai',
      title: 'Refactor value',
      description: null,
      status: 'pending',
      snapshot_hash: null,
      verification_commands: [],
      verification: [],
      created_at: 1,
      updated_at: 1,
      files: [],
    } satisfies ChangeSetResponse
    api.runEditorAction.mockResolvedValue({
      kind: 'changes',
      summary: 'Refactor value',
      explanation: null,
      verification_commands: [],
      context: {},
      change_set: changeSet,
      findings: [],
    })
    const close = vi.fn()
    render(
      <EditorAiActionDialog
        workspace="/repo"
        request={request}
        onClose={close}
      />,
    )
    await screen.findByText('active_file · editor-buffer')

    fireEvent.click(screen.getByRole('button', { name: 'Run explicit action' }))

    await waitFor(() => expect(api.runEditorAction).toHaveBeenCalled())
    expect(api.runEditorAction).toHaveBeenCalledWith('/repo', {
      ...request,
      instruction: undefined,
      mention_paths: [],
      expected_context_sha256: 'c'.repeat(64),
    })
    expect(useChangeSetStore.getState().active?.id).toBe('change-1')
    expect(close).toHaveBeenCalled()
  })
})
