import { describe, expect, it } from 'vitest'

import {
  buildThinkingOptions,
  reconcileThinkingLevel,
} from '@/lib/model-settings'
import { thinkingLevelSchema } from '@/components/settings/schema'

describe('shared model settings', () => {
  it('builds the same labelled thinking choices for every model picker', () => {
    expect(
      buildThinkingOptions(['none', 'minimal', 'xhigh', 'max', 'ultra']),
    ).toEqual([
      { value: null, label: 'Default', mark: 'Def' },
      { value: 'none', label: 'None', mark: 'None' },
      { value: 'minimal', label: 'Minimal', mark: 'Min' },
      { value: 'xhigh', label: 'X-High', mark: 'XH' },
      { value: 'max', label: 'Max', mark: 'Max' },
      { value: 'ultra', label: 'Ultra', mark: 'Ult' },
    ])
  })

  it('preserves a thinking level only when the newly selected model supports it', () => {
    const model = { thinking_levels: ['low', 'high'] }

    expect(reconcileThinkingLevel('high', model)).toBe('high')
    expect(reconcileThinkingLevel('ultra', model)).toBeNull()
    expect(reconcileThinkingLevel(null, model)).toBeNull()
    expect(reconcileThinkingLevel('low', undefined)).toBeNull()
  })

  it('accepts registry-advertised and future thinking levels in agent validation', () => {
    for (const level of ['minimal', 'xhigh', 'max', 'ultra', 'provider-future']) {
      expect(thinkingLevelSchema.safeParse(level).success).toBe(true)
    }
  })
})
