import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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
import type { SSECallbacks } from '@/api/sse'

function historyResponse(running: boolean) {
  return {
    lead: { id: 'session-1', agent_name: 'lead', messages: [], running },
    members: [],
    goal: null,
    has_more: false,
    next_cursor: null,
  }
}

/** Wires up a session whose turn is in flight and returns the stream's callbacks. */
async function connectRunningSession(): Promise<SSECallbacks> {
  let callbacks!: SSECallbacks
  apiMocks.teamStream.mockImplementation((_sessionId: string, cb: SSECallbacks) => {
    callbacks = cb
  })
  useTeamStore.getState().beginResolvedSession('session-1', { mode: 'work' })
  await useTeamStore.getState().loadSession('session-1', null, null)
  useTeamStore.getState().connectStream()
  return callbacks
}

describe('useTeamStore stream reconnect', () => {
  beforeEach(() => {
    queryClient.clear()
    vi.clearAllMocks()
    vi.useFakeTimers()
    apiMocks.getRegistry.mockResolvedValue({ models: [] })
    apiMocks.listTeamAgents.mockResolvedValue({
      agents: [{ name: 'lead', is_lead: true, model: null }],
      blueprints: [],
    })
    apiMocks.teamHistory.mockResolvedValue(historyResponse(true))
    useTeamStore.getState().beginResolvedSession(null)
  })

  afterEach(() => {
    // The reconnect backoff is a module-level counter (proof of life is what
    // resets it in production too), so drive one to keep tests independent
    // of each other regardless of run order.
    const lastCall = apiMocks.teamStream.mock.calls.at(-1)
    ;(lastCall?.[1] as SSECallbacks | undefined)?.onEvent('agent_status', { agent: 'lead', status: 'idle' })
    vi.useRealTimers()
  })

  it('recovers a stream dropped by a transient network error while a turn is running', async () => {
    const callbacks = await connectRunningSession()
    expect(apiMocks.teamStream).toHaveBeenCalledTimes(1)

    callbacks.onError?.(new Error('Failed to fetch'))
    expect(useTeamStore.getState().isConnected).toBe(false)
    // A dropped socket must not itself end the turn.
    expect(useTeamStore.getState().isTeamWorking).toBe(true)

    await vi.advanceTimersByTimeAsync(1_000)

    expect(apiMocks.teamHistory).toHaveBeenCalledTimes(2)
    expect(apiMocks.teamStream).toHaveBeenCalledTimes(2)
    expect(useTeamStore.getState().isConnected).toBe(true)
  })

  it('recovers a stream that closed without a terminal event mid-turn', async () => {
    const callbacks = await connectRunningSession()

    // No `done`/`error` SSE event ever arrived, so `isTeamWorking` is still
    // true — the body just ended (dropped connection, not a finished turn).
    callbacks.onDone?.()
    expect(useTeamStore.getState().isConnected).toBe(false)

    await vi.advanceTimersByTimeAsync(1_000)

    expect(apiMocks.teamStream).toHaveBeenCalledTimes(2)
    expect(useTeamStore.getState().isConnected).toBe(true)
  })

  it('does not schedule a reconnect for a genuine (non-network) stream error', async () => {
    const callbacks = await connectRunningSession()

    callbacks.onError?.(new Error('boom: unexpected server response'))
    expect(useTeamStore.getState().error).toBe('boom: unexpected server response')

    await vi.advanceTimersByTimeAsync(20_000)

    expect(apiMocks.teamStream).toHaveBeenCalledTimes(1)
  })

  it('resets the backoff once data flows again, instead of growing across unrelated drops', async () => {
    const first = await connectRunningSession()

    first.onError?.(new Error('Failed to fetch'))
    await vi.advanceTimersByTimeAsync(1_000)
    expect(apiMocks.teamStream).toHaveBeenCalledTimes(2)

    // The reconnect succeeded and is receiving events again — this must
    // count as proof of life, not as "still the same failure".
    const second = apiMocks.teamStream.mock.calls[1][1] as SSECallbacks
    second.onEvent('agent_status', { agent: 'lead', status: 'working' })

    second.onError?.(new Error('Failed to fetch'))
    // If the backoff had kept growing from the first drop, 1s would not be
    // enough yet for a second attempt.
    await vi.advanceTimersByTimeAsync(1_000)
    expect(apiMocks.teamStream).toHaveBeenCalledTimes(3)
  })
})
