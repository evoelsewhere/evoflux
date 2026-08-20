import { describe, expect, it } from 'vitest'

import {
  formatCreditBalance,
  formatProviderPlan,
  formatUsageReset,
  formatUsageWindowLabel,
  summarizeCreditUsage,
} from '@/utils/provider-usage'

describe('provider usage formatting', () => {
  it('presents internal Codex enterprise plan identifiers for users', () => {
    expect(formatProviderPlan('enterprise_cbp_usage_based')).toBe('Enterprise usage-based')
    expect(formatProviderPlan('pro')).toBe('Pro')
  })

  it('keeps credit balances readable without leaking backend precision', () => {
    expect(formatCreditBalance('33624.47638952732', 'en-US')).toBe('33,624.48')
    expect(formatCreditBalance('257/300', 'en-US')).toBe('257 / 300')
  })

  it('preserves an unknown non-numeric balance', () => {
    expect(formatCreditBalance('available')).toBe('available')
  })

  it('formats absolute credit usage only when total data is available', () => {
    expect(summarizeCreditUsage({ used: '171527', total: '200000' }, 'en-US')).toEqual({
      used: 171527,
      total: 200000,
      usedPercent: 85.7635,
      unit: 'credits',
      label: '171,527 of 200,000 credits used',
    })
    expect(summarizeCreditUsage({ balance: '28473/200000' }, 'en-US')?.label).toBe(
      '171,527 of 200,000 credits used',
    )
    expect(summarizeCreditUsage({ balance: '115125.62' }, 'en-US')).toBeNull()
  })

  it('labels long quota windows and reset dates like account usage', () => {
    const resetAt = Date.UTC(2026, 8, 1) / 1000

    expect(formatUsageWindowLabel('Codex', 30 * 24 * 60)).toBe('Monthly usage')
    expect(formatUsageWindowLabel('Codex', 7 * 24 * 60)).toBe('Weekly usage')
    expect(formatUsageWindowLabel('Premium requests', 30 * 24 * 60)).toBe(
      'Monthly premium requests',
    )
    expect(formatUsageReset(resetAt, 30 * 24 * 60, 'en-US', 'UTC')).toBe(
      'Resets Sep 1',
    )
  })

  it('uses the provider quota unit instead of calling every limit credits', () => {
    expect(
      summarizeCreditUsage(
        { used: '43', total: '300', unit: 'premium requests' },
        'en-US',
      )?.label,
    ).toBe('43 of 300 premium requests used')
  })
})
