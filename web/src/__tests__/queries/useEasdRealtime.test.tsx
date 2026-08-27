import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { SSECallbacks } from '@/api/sse'
import { useEasdRealtime } from '@/queries/useEasdRealtime'

const api = vi.hoisted(() => ({
  stream: vi.fn(),
  callbacks: null as SSECallbacks | null,
}))

vi.mock('@/api/client', () => ({
  easdRunStream: (
    _runId: string,
    _afterSequence: number,
    _clientId: string,
    callbacks: SSECallbacks,
  ) => {
    api.callbacks = callbacks
    api.stream(_runId, _afterSequence, _clientId)
  },
}))

function wrapper(client: QueryClient) {
  return function QueryWrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useEasdRealtime', () => {
  beforeEach(() => {
    api.stream.mockReset()
    api.callbacks = null
  })

  it('deduplicates event sequences and invalidates existing query projections', async () => {
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries').mockResolvedValue(undefined)
    const { result } = renderHook(() => useEasdRealtime('run-1'), {
      wrapper: wrapper(client),
    })
    expect(api.stream).toHaveBeenCalledWith('run-1', 0, expect.any(String))

    act(() => api.callbacks?.onEvent('easd_presence', {
      type: 'easd_presence',
      run_id: 'run-1',
      client_ids: ['one', 'two'],
      count: 2,
    }))
    expect(result.current.status).toBe('live')
    expect(result.current.viewerCount).toBe(2)

    act(() => api.callbacks?.onEvent('easd_event', {
      type: 'easd_event',
      run_id: 'run-1',
      sequence: 8,
      repository_generation: 8,
      event: { event: 'review_retried', sequence: 8 },
    }))
    expect(invalidate).toHaveBeenCalledTimes(4)

    act(() => api.callbacks?.onEvent('easd_event', {
      type: 'easd_event',
      run_id: 'run-1',
      sequence: 8,
      repository_generation: 8,
      event: { event: 'review_retried', sequence: 8 },
    }))
    expect(invalidate).toHaveBeenCalledTimes(4)
  })

  it('forces query resync after broker overflow', () => {
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries').mockResolvedValue(undefined)
    renderHook(() => useEasdRealtime('run-1'), { wrapper: wrapper(client) })

    act(() => api.callbacks?.onEvent('easd_resync_required', {
      type: 'easd_resync_required',
      run_id: 'run-1',
      reason: 'subscriber_queue_overflow',
    }))

    expect(invalidate).toHaveBeenCalledTimes(4)
  })

  it('reconnects from the last delivered sequence', () => {
    vi.useFakeTimers()
    const client = new QueryClient()
    const { result, unmount } = renderHook(() => useEasdRealtime('run-1'), {
      wrapper: wrapper(client),
    })
    act(() => api.callbacks?.onEvent('easd_event', {
      type: 'easd_event',
      run_id: 'run-1',
      sequence: 8,
      repository_generation: 8,
      event: { event: 'review_retried', sequence: 8 },
    }))
    act(() => api.callbacks?.onError?.(new Error('connection lost')))
    expect(result.current.status).toBe('reconnecting')

    act(() => vi.advanceTimersByTime(1_000))

    expect(api.stream).toHaveBeenLastCalledWith('run-1', 8, expect.any(String))
    unmount()
    vi.useRealTimers()
  })
})
