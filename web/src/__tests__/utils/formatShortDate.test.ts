import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { formatShortDate } from '@/utils/format'

describe('formatShortDate', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 8, 28, 16, 0))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows only the time for today', () => {
    expect(formatShortDate(new Date(2026, 8, 28, 6, 59).toISOString())).toBe('06:59')
  })

  it('says Yesterday without a time', () => {
    expect(formatShortDate(new Date(2026, 8, 27, 14, 29).toISOString())).toBe('Yesterday')
  })

  it('drops the year within the current year and keeps it before', () => {
    const thisYear = formatShortDate(new Date(2026, 8, 5, 21, 10).toISOString())
    const lastYear = formatShortDate(new Date(2025, 8, 5, 21, 10).toISOString())

    expect(thisYear).not.toMatch(/2026/)
    expect(thisYear).toMatch(/5/)
    expect(lastYear).toMatch(/2025/)
  })

  it('is empty without a date', () => {
    expect(formatShortDate(null)).toBe('')
  })
})
