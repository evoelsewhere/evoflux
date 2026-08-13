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

import { queryClient } from '@/lib/query-client'
import { useTeamStore } from '@/stores/useTeamStore'

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

describe('useTeamStore request coalescing', () => {
  it('shares one in-flight session restore for the same generation', async () => {
    let rejectHistory!: (error: Error) => void
    apiMocks.teamHistory.mockImplementation(
      () => new Promise((_resolve, reject) => {
        rejectHistory = reject
      }),
    )

    useTeamStore.getState().beginResolvedSession('session-1', { mode: 'work' })
    const first = useTeamStore.getState().loadSession('session-1', null, null)
    const second = useTeamStore.getState().loadSession('session-1', null, null)

    expect(second).toBe(first)
    expect(apiMocks.teamHistory).toHaveBeenCalledTimes(1)
    expect(apiMocks.listTeamAgents).toHaveBeenCalledTimes(1)

    rejectHistory(new Error('stop test request'))
    await Promise.all([first, second])
  })

  it('does not let a slower roster from the previous mode overwrite the latest mode', async () => {
    const resolvers = new Map<string | null | undefined, (value: unknown) => void>()
    apiMocks.listTeamAgents.mockImplementation(
      (_workspace: string | null | undefined, mode: string | null | undefined) =>
        new Promise((resolve) => {
          resolvers.set(mode, resolve)
        }),
    )

    const coding = useTeamStore.getState().loadTeamStatus('/repo', 'coding')
    const work = useTeamStore.getState().loadTeamStatus(null, null)

    // Resolve the later (work) request first, then the slower coding request.
    // The stale coding roster must not overwrite the latest lead.
    resolvers.get(null)?.({
      agents: [{ name: 'work-lead', is_lead: true, model: 'work-model' }],
      blueprints: [],
    })
    await work

    resolvers.get('coding')?.({
      agents: [{ name: 'coding-lead', is_lead: true, model: 'coding-model' }],
      blueprints: [],
    })
    await coding

    expect(useTeamStore.getState().leadName).toBe('work-lead')
    expect(apiMocks.listTeamAgents).toHaveBeenCalledTimes(2)
  })

  it('aborts a stale history request when the active session changes', async () => {
    let firstSignal: AbortSignal | undefined
    apiMocks.teamHistory
      .mockImplementationOnce((_id, _before, signal: AbortSignal) => {
        firstSignal = signal
        return new Promise((_resolve, reject) => {
          signal.addEventListener(
            'abort',
            () => reject(new DOMException('aborted', 'AbortError')),
            { once: true },
          )
        })
      })
      .mockResolvedValueOnce({
        lead: {
          id: 'session-2',
          agent_name: 'lead',
          permission_mode: 'ask',
          messages: [],
          running: false,
        },
        members: [],
        goal: null,
        has_more: false,
        next_cursor: null,
      })

    useTeamStore.getState().beginResolvedSession('session-1', { mode: 'work' })
    const stale = useTeamStore.getState().loadSession('session-1', null, null)
    useTeamStore.getState().beginResolvedSession('session-2', { mode: 'work' })
    const current = useTeamStore.getState().loadSession('session-2', null, null)

    await Promise.all([stale, current])

    expect(firstSignal?.aborted).toBe(true)
    expect(useTeamStore.getState().sessionId).toBe('session-2')
    expect(useTeamStore.getState().sessionPermissionMode).toBe('ask')
  })
})

describe('useTeamStore goal state', () => {
  const goal = {
    session_id: 'session-1',
    objective: 'Finish the migration',
    status: 'active' as const,
    token_budget: 20_000,
    tokens_used: 400,
    time_used_seconds: 12,
    pause_reason: null,
    blocker_streak: 0,
    status_details: null,
    version: 1,
    created_at: '2026-07-31T00:00:00Z',
    updated_at: '2026-07-31T00:00:12Z',
    completed_at: null,
  }

  it('restores a durable goal from session history', async () => {
    apiMocks.teamHistory.mockResolvedValue({
      lead: {
        id: 'session-1',
        agent_name: 'lead',
        messages: [],
        running: false,
      },
      members: [],
      goal,
      has_more: false,
      next_cursor: null,
    })

    useTeamStore.getState().beginResolvedSession('session-1', { mode: 'work' })
    await useTeamStore.getState().loadSession('session-1', null, null)

    expect(useTeamStore.getState().activeGoal).toEqual(goal)
  })

  it('applies and clears goal snapshots from SSE', () => {
    useTeamStore.getState()._handleSSEEvent('goal_status', { goal })
    expect(useTeamStore.getState().activeGoal).toEqual(goal)

    useTeamStore.getState()._handleSSEEvent('goal_status', { goal: null })
    expect(useTeamStore.getState().activeGoal).toBeNull()
  })
})
