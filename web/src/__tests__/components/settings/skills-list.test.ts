import { describe, expect, it } from 'vitest'

import {
  resolveRequestedSkillMode,
  resolveSkillDetailMode,
} from '@/lib/skill-detail-mode'

describe('skill list detail scope', () => {
  it('does not infer a detail mode when navigation omitted one', () => {
    expect(resolveRequestedSkillMode(undefined)).toBeNull()
    expect(resolveRequestedSkillMode('all')).toBeNull()
    expect(resolveRequestedSkillMode('coding')).toBe('coding')
    expect(resolveRequestedSkillMode('aim')).toBe('aim')
  })

  it('keeps invalid rows unscoped so mode discovery cannot replace the selected candidate', () => {
    expect(
      resolveSkillDetailMode({
        valid: false,
        modes: ['coding'],
        modeFilter: 'coding',
        workspaceScoped: true,
      }),
    ).toBeNull()
  })

  it('keeps valid rows scoped to an explicit filter or a single available mode', () => {
    expect(
      resolveSkillDetailMode({
        valid: true,
        modes: ['work', 'coding'],
        modeFilter: 'work',
        workspaceScoped: true,
      }),
    ).toBe('work')
    expect(
      resolveSkillDetailMode({
        valid: true,
        modes: ['coding'],
        modeFilter: 'all',
        workspaceScoped: false,
      }),
    ).toBe('coding')
  })

  it('uses AIM filters directly and picks an available mode for workspace-scoped subsets', () => {
    expect(
      resolveSkillDetailMode({
        valid: true,
        modes: ['work', 'aim'],
        modeFilter: 'aim',
        workspaceScoped: true,
      }),
    ).toBe('aim')
    expect(
      resolveSkillDetailMode({
        valid: true,
        modes: ['work', 'aim'],
        modeFilter: 'all-modes',
        workspaceScoped: true,
      }),
    ).toBe('work')
  })
})
