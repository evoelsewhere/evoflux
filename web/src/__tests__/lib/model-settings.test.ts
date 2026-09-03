import { describe, expect, it } from 'vitest'

import {
  buildThinkingOptions,
  fastModePriceHint,
  formatModelPrice,
  formatTokenCount,
  normalizeModelId,
  PROVIDER_MODEL_PLACEHOLDER,
  reconcileThinkingLevel,
  supportsFastMode,
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

  // BUG-002: the composer's model picker showed the raw internal
  // "__PROVIDER_MODEL__" sentinel (leaked verbatim by GET /api/team/leads
  // for a lead with no per-agent model override) instead of falling back
  // to "Default"/"Model" the same way it does for a genuinely unset model.
  it('normalizeModelId treats the provider-model placeholder as no model configured', () => {
    expect(normalizeModelId(PROVIDER_MODEL_PLACEHOLDER)).toBeNull()
    expect(normalizeModelId(null)).toBeNull()
    expect(normalizeModelId(undefined)).toBeNull()
    expect(normalizeModelId('')).toBeNull()
    expect(normalizeModelId('anthropic:claude-sonnet-5')).toBe('anthropic:claude-sonnet-5')
  })

  it('SessionPillsRow-style effectiveModel resolution falls back to the default when both session and default model are the placeholder', () => {
    // Mirrors AdvancedComposerControl's effectiveModel computation in
    // SessionPillsRow.tsx: a session model wins over the default, but a
    // placeholder in either position is treated as absent so the composer
    // renders its "Model"/"Default" fallback copy instead of the raw token.
    const resolve = (sessionModel: string | null, defaultModel: string | null) =>
      normalizeModelId(sessionModel) ?? normalizeModelId(defaultModel) ?? ''

    expect(resolve(null, PROVIDER_MODEL_PLACEHOLDER)).toBe('')
    expect(resolve(PROVIDER_MODEL_PLACEHOLDER, PROVIDER_MODEL_PLACEHOLDER)).toBe('')
    expect(resolve(null, 'xiaomi:mimo-v2.5')).toBe('xiaomi:mimo-v2.5')
    expect(resolve('anthropic:claude-sonnet-5', PROVIDER_MODEL_PLACEHOLDER)).toBe(
      'anthropic:claude-sonnet-5',
    )
  })
})

describe('catalogue facts in the pickers', () => {
  it('reads fast-mode availability from the model, not its provider prefix', () => {
    // This used to test for a `codex:` prefix, which meant a fast-capable
    // model from any other provider silently had no toggle.
    expect(supportsFastMode({ modes: ['fast'] })).toBe(true)
    expect(supportsFastMode({ modes: [] })).toBe(false)
    expect(supportsFastMode({})).toBe(false)
    expect(supportsFastMode(undefined)).toBe(false)
  })

  it('states what the fast lane costs, because it is not the same price', () => {
    expect(fastModePriceHint({ mode_cost_multiplier: { fast: 2.5 } })).toBe('2.5×')
    expect(fastModePriceHint({ mode_cost_multiplier: { fast: 2 } })).toBe('2×')
  })

  it('says nothing rather than implying parity when no rate is published', () => {
    // "Unknown" and "same price" are different answers, and a Fast toggle is
    // the wrong control to get that wrong on.
    expect(fastModePriceHint({ mode_cost_multiplier: {} })).toBe('')
    expect(fastModePriceHint({ mode_cost_multiplier: { fast: 1 } })).toBe('')
    expect(fastModePriceHint(undefined)).toBe('')
  })

  it('formats a context window at a glance rather than exactly', () => {
    expect(formatTokenCount(1_048_576)).toBe('1M')
    expect(formatTokenCount(272_000)).toBe('272K')
    expect(formatTokenCount(0)).toBe('')
    expect(formatTokenCount(null)).toBe('')
  })

  it('prices a model per million tokens, and says free when it is', () => {
    expect(formatModelPrice({ input: 3, output: 15 })).toBe('$3/$15')
    expect(formatModelPrice({ input: 0, output: 0 })).toBe('free')
  })

  it('omits a price the catalogue does not quote', () => {
    // A local or newly listed model has no rate; `$0/$0` would assert one.
    expect(formatModelPrice({})).toBe('')
    expect(formatModelPrice(undefined)).toBe('')
  })
})
