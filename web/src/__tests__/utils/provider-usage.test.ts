import { describe, expect, it } from 'vitest'

import { formatCreditBalance, formatProviderPlan } from '@/utils/provider-usage'

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
})
