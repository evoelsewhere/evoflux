import { describe, expect, it } from 'vitest'

import {
  HISTORY_INITIAL_RENDERED_TURNS,
  HISTORY_RENDER_STEP,
  historyLoadRearmThreshold,
  historyLoadThreshold,
  shouldPrimeOlderHistory,
} from '@/utils/transcript-history'

describe('transcript history look-ahead', () => {
  it('keeps three viewports of upward loading buffer with a desktop minimum', () => {
    expect(historyLoadThreshold(400)).toBe(1_600)
    expect(historyLoadThreshold(700)).toBe(2_100)
    expect(historyLoadThreshold(1_000)).toBe(3_000)
    expect(historyLoadRearmThreshold(700)).toBe(2_900)
  })

  it('primes a short server-backed transcript but not a deep local buffer', () => {
    expect(shouldPrimeOlderHistory({
      canLoadOlder: true,
      clientHeight: 700,
      scrollHeight: 2_500,
    })).toBe(true)
    expect(shouldPrimeOlderHistory({
      canLoadOlder: true,
      clientHeight: 700,
      scrollHeight: 4_000,
    })).toBe(false)
    expect(shouldPrimeOlderHistory({
      canLoadOlder: false,
      clientHeight: 700,
      scrollHeight: 1_000,
    })).toBe(false)
  })

  it('renders a larger bounded window and reveal batch', () => {
    expect(HISTORY_INITIAL_RENDERED_TURNS).toBe(72)
    expect(HISTORY_RENDER_STEP).toBe(24)
  })
})
