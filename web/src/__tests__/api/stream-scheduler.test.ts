import { afterEach, describe, expect, it, vi } from 'vitest'

import { createStreamScheduler } from '@/api/stream-scheduler'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('createStreamScheduler', () => {
  it('coalesces adjacent text deltas into one paint update', () => {
    let paint: FrameRequestCallback | undefined
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      paint = callback
      return 1
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    const dispatch = vi.fn()
    const scheduler = createStreamScheduler(dispatch)

    scheduler.push('message', { agent: 'lead', text: 'Hello' })
    scheduler.push('message', { agent: 'lead', text: ' world' })

    expect(dispatch).not.toHaveBeenCalled()
    paint?.(16)
    expect(dispatch).toHaveBeenCalledOnce()
    expect(dispatch).toHaveBeenCalledWith('message', { agent: 'lead', text: 'Hello world' })
  })

  it('flushes visual deltas before structural events', () => {
    vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    const dispatch = vi.fn()
    const scheduler = createStreamScheduler(dispatch)

    scheduler.push('thinking', { agent: 'lead', text: 'Checking' })
    scheduler.push('tool_start', { agent: 'lead', name: 'read' })

    expect(dispatch.mock.calls.map(([type]) => type)).toEqual(['thinking', 'tool_start'])
  })

  it('keeps deltas for different agents in wire order', () => {
    vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    const dispatch = vi.fn()
    const scheduler = createStreamScheduler(dispatch)

    scheduler.push('message', { agent: 'lead', text: 'a' })
    scheduler.push('message', { agent: 'reviewer', text: 'b' })
    scheduler.flush()

    expect(dispatch.mock.calls.map(([, data]) => data)).toEqual([
      { agent: 'lead', text: 'a' },
      { agent: 'reviewer', text: 'b' },
    ])
  })
})
