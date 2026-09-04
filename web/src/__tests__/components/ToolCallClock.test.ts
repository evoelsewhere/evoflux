import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import { subscribeClock } from '@/components/ToolCall'

/**
 * The shared clock replaced one 100 ms interval per running ToolCall. It must
 * clean up everything it registers: an earlier version removed the interval
 * but left its `visibilitychange` listener attached, so every start/stop cycle
 * — one per burst of tool calls — leaked another listener on `document`.
 */
describe('ToolCall shared clock', () => {
  let added: number
  let removed: number
  let addSpy: ReturnType<typeof vi.spyOn>
  let removeSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    vi.useFakeTimers()
    added = 0
    removed = 0
    addSpy = vi
      .spyOn(document, 'addEventListener')
      .mockImplementation(((type: string) => {
        if (type === 'visibilitychange') added += 1
      }) as never)
    removeSpy = vi
      .spyOn(document, 'removeEventListener')
      .mockImplementation(((type: string) => {
        if (type === 'visibilitychange') removed += 1
      }) as never)
  })

  afterEach(() => {
    addSpy.mockRestore()
    removeSpy.mockRestore()
    vi.useRealTimers()
  })

  it('removes its visibilitychange listener when the last subscriber leaves', () => {
    for (let i = 0; i < 5; i += 1) {
      const unsubscribe = subscribeClock(() => {})
      unsubscribe()
    }
    expect(added).toBe(5)
    expect(removed).toBe(5)
  })

  it('registers only one listener while subscribers overlap', () => {
    const a = subscribeClock(() => {})
    const b = subscribeClock(() => {})
    const c = subscribeClock(() => {})
    expect(added).toBe(1)

    a()
    b()
    expect(removed).toBe(0) // still one subscriber left

    c()
    expect(removed).toBe(1)
  })

  it('ticks subscribers on a sub-second cadence', () => {
    const seen: number[] = []
    const unsubscribe = subscribeClock((now) => seen.push(now))

    vi.advanceTimersByTime(1000)
    unsubscribe()

    // A 1 s tick would fire once here; the elapsed label renders tenths
    // below 10 s, so it needs to update more often than that.
    expect(seen.length).toBeGreaterThan(1)
  })

  it('stops ticking after unsubscribe', () => {
    const seen: number[] = []
    const unsubscribe = subscribeClock((now) => seen.push(now))
    vi.advanceTimersByTime(500)
    const before = seen.length
    unsubscribe()
    vi.advanceTimersByTime(2000)
    expect(seen.length).toBe(before)
  })
})
