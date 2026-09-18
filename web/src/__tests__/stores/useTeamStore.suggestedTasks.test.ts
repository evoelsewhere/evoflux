import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMocks = vi.hoisted(() => ({
  cancelQueuedTeamMessage: vi.fn(),
  getRegistry: vi.fn(),
  listTeamAgents: vi.fn(),
  postTeamChat: vi.fn(),
  postTeamCommand: vi.fn(),
  teamHistory: vi.fn(),
  teamStream: vi.fn(),
}))

vi.mock('@/api/client', () => apiMocks)

import type { SuggestedTask } from '@/api/types'
import { queryClient } from '@/lib/query-client'
import { useTeamStore } from '@/stores/useTeamStore'

function makeTask(overrides: Partial<SuggestedTask> = {}): SuggestedTask {
  return {
    id: 'task-1',
    session_id: 'session-1',
    title: 'Fix flaky uuid7 test',
    tldr: 'Noticed it while running the suite.',
    prompt: 'Long, self-contained instruction with file paths.',
    cwd: null,
    status: 'pending',
    spawned_session_id: null,
    worktree_path: null,
    dismiss_reason: null,
    created_at: '2026-09-15T00:00:00Z',
    updated_at: '2026-09-15T00:00:00Z',
    ...overrides,
  }
}

beforeEach(() => {
  queryClient.clear()
  vi.clearAllMocks()
  apiMocks.getRegistry.mockResolvedValue({ models: [] })
  apiMocks.listTeamAgents.mockResolvedValue({
    agents: [{ name: 'lead', is_lead: true, model: null }],
    blueprints: [],
  })
  useTeamStore.getState().beginResolvedSession(null)
})

describe('suggested task SSE events', () => {
  it('adds a pending chip', () => {
    const task = makeTask()

    useTeamStore.getState()._handleSSEEvent('suggested_task', { task })

    expect(useTeamStore.getState().suggestedTasks).toEqual([task])
  })

  it('upserts rather than duplicating a chip it already has', () => {
    const task = makeTask()
    const handle = useTeamStore.getState()._handleSSEEvent
    handle('suggested_task', { task })

    handle('suggested_task', { task: { ...task, tldr: 'Reworded.' } })

    const tasks = useTeamStore.getState().suggestedTasks
    expect(tasks).toHaveLength(1)
    expect(tasks[0].tldr).toBe('Reworded.')
  })

  it('drops a chip that left pending', () => {
    const task = makeTask()
    const handle = useTeamStore.getState()._handleSSEEvent
    handle('suggested_task', { task })
    handle('suggested_task', { task: makeTask({ id: 'task-2' }) })

    handle('suggested_task', {
      task: { ...task, status: 'started', spawned_session_id: 'session-2' },
    })

    expect(useTeamStore.getState().suggestedTasks.map((t) => t.id)).toEqual(['task-2'])
  })

  it('ignores a malformed payload', () => {
    useTeamStore.getState()._handleSSEEvent('suggested_task', { task: {} })

    expect(useTeamStore.getState().suggestedTasks).toEqual([])
  })

  it('clears chips when the session changes', () => {
    useTeamStore.getState()._handleSSEEvent('suggested_task', { task: makeTask() })

    useTeamStore.getState().beginResolvedSession('session-9', { mode: 'coding' })

    expect(useTeamStore.getState().suggestedTasks).toEqual([])
  })
})
