/**
 * An idle session's stream closes as soon as it opens (the backend has no
 * turn to attach to). Tab refocus must not turn that into a reconnect loop
 * that also refetches every session list each time.
 */
import { act, renderHook } from '@testing-library/react'
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

import { IDLE_RESUME_MIN_INTERVAL_MS, useTeamSse } from '@/components/TeamChatView/useTeamSse'
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

function lastStreamCallbacks(): SSECallbacks {
  return apiMocks.teamStream.mock.calls.at(-1)?.[1] as SSECallbacks
}

function sessionInvalidations(): number {
  return useTeamStore.getState().cacheInvalidations.filter((e) => e.kind === 'team_sessions').length
}

function refocusTab() {
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'))
  })
}

async function mountOn(sessionId: string) {
  const hook = renderHook(() =>
    useTeamSse({
      sessionId,
      agentWorkspace: null,
      hasCodingWorkspace: false,
      isCodingSessionLoading: false,
      mode: 'work',
    }),
  )
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
  return hook
}

describe('useTeamSse on an idle session', () => {
  beforeEach(() => {
    queryClient.clear()
    vi.clearAllMocks()
    vi.useFakeTimers()
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
    apiMocks.getRegistry.mockResolvedValue({ models: [] })
    apiMocks.listTeamAgents.mockResolvedValue({
      agents: [{ name: 'lead', is_lead: true, model: null }],
      blueprints: [],
    })
    apiMocks.teamHistory.mockResolvedValue(historyResponse(false))
    useTeamStore.getState().beginResolvedSession(null)
    useTeamStore.setState({ cacheInvalidations: [] })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('does not invalidate session lists when an idle attach closes empty', async () => {
    const hook = await mountOn('session-1')
    expect(apiMocks.teamStream).toHaveBeenCalledTimes(1)

    act(() => lastStreamCallbacks().onDone?.())

    expect(useTeamStore.getState().isConnected).toBe(false)
    expect(sessionInvalidations()).toBe(0)
    hook.unmount()
  })

  it('still invalidates session lists when the stream delivered events', async () => {
    const hook = await mountOn('session-1')

    act(() => {
      lastStreamCallbacks().onEvent('agent_status', { agent: 'lead', status: 'idle' })
      lastStreamCallbacks().onDone?.()
    })

    expect(sessionInvalidations()).toBe(1)
    hook.unmount()
  })

  it('throttles idle re-attach on repeated tab refocus', async () => {
    // Like the real backend: every idle attach ends at once, empty.
    apiMocks.teamStream.mockImplementation((_sid: string, cb: SSECallbacks) => {
      queueMicrotask(() => cb.onDone?.())
    })
    const hook = await mountOn('session-1')
    expect(apiMocks.teamStream).toHaveBeenCalledTimes(1)
    expect(useTeamStore.getState().isConnected).toBe(false)

    // Refocus every 5s for just under the window — the observed loop.
    for (let i = 0; i < 5; i++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000)
      })
      refocusTab()
    }
    expect(apiMocks.teamStream).toHaveBeenCalledTimes(1)

    // Once the window has passed, a refocus re-checks exactly once.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(IDLE_RESUME_MIN_INTERVAL_MS)
    })
    refocusTab()
    refocusTab()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(apiMocks.teamStream).toHaveBeenCalledTimes(2)
    expect(sessionInvalidations()).toBe(0)
    hook.unmount()
  })

  it('resumes immediately on refocus while a turn is running', async () => {
    apiMocks.teamHistory.mockResolvedValue(historyResponse(true))
    const hook = await mountOn('session-1')
    expect(useTeamStore.getState().isTeamWorking).toBe(true)

    // Simulate the socket dying while the tab was hidden.
    act(() => {
      useTeamStore.getState()._abortController?.abort()
      useTeamStore.setState({ isConnected: false })
    })
    refocusTab()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(apiMocks.teamStream).toHaveBeenCalledTimes(2)
    hook.unmount()
  })
})
