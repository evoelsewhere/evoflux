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

    useTeamStore.getState().beginResolvedSession('session-1', { mode: 'forge' })
    const first = useTeamStore.getState().loadSession('session-1', null, null)
    const second = useTeamStore.getState().loadSession('session-1', null, null)

    expect(second).toBe(first)
    expect(apiMocks.teamHistory).toHaveBeenCalledTimes(1)
    expect(apiMocks.listTeamAgents).toHaveBeenCalledTimes(1)

    rejectHistory(new Error('stop test request'))
    await Promise.all([first, second])
  })

  it('does not let a slower roster from the previous mode overwrite the latest mode', async () => {
    const resolvers = new Map<string, (value: unknown) => void>()
    apiMocks.listTeamAgents.mockImplementation(
      (_workspace: string, mode: string) =>
        new Promise((resolve) => {
          resolvers.set(mode, resolve)
        }),
    )

    const coding = useTeamStore.getState().loadTeamStatus('/repo', 'coding')
    const aim = useTeamStore.getState().loadTeamStatus('/repo', 'aim')

    resolvers.get('aim')?.({
      agents: [{ name: 'aim-lead', is_lead: true, model: 'aim-model' }],
      blueprints: [],
    })
    await aim

    resolvers.get('coding')?.({
      agents: [{ name: 'coding-lead', is_lead: true, model: 'coding-model' }],
      blueprints: [],
    })
    await coding

    expect(useTeamStore.getState().leadName).toBe('aim-lead')
    expect(apiMocks.listTeamAgents).toHaveBeenCalledTimes(2)
  })
})
