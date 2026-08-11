import { describe, expect, it } from 'vitest'

import {
  ALL_SKILL_MODES,
  hasAllSkillModes,
  normalizeSkillModes,
  skillAvailabilityLabel,
  skillModesEqual,
} from '@/lib/skill-modes'

describe('skill mode helpers', () => {
  it('normalizes API modes without losing partial combinations', () => {
    expect(normalizeSkillModes(['aim', 'work', 'aim'])).toEqual(['work', 'aim'])
    expect(normalizeSkillModes(['coding', 'aim'])).toEqual(['coding', 'aim'])
  })

  it('defaults missing modes to every supported mode', () => {
    expect(normalizeSkillModes()).toEqual(ALL_SKILL_MODES)
    expect(normalizeSkillModes([])).toEqual(ALL_SKILL_MODES)
    expect(hasAllSkillModes(['aim', 'work', 'coding'])).toBe(true)
  })

  it('compares canonical mode sets', () => {
    expect(skillModesEqual(['aim', 'work'], ['work', 'aim'])).toBe(true)
    expect(skillModesEqual(['work', 'coding'], ALL_SKILL_MODES)).toBe(false)
  })

  it('renders explicit management labels', () => {
    expect(skillAvailabilityLabel(['work'])).toBe('Work only')
    expect(skillAvailabilityLabel(['coding'])).toBe('Coding only')
    expect(skillAvailabilityLabel(['aim'])).toBe('AIM only')
    expect(skillAvailabilityLabel(['work', 'coding'])).toBe('Work + Coding')
    expect(skillAvailabilityLabel(['work', 'aim'])).toBe('Work + AIM')
    expect(skillAvailabilityLabel(['coding', 'aim'])).toBe('Coding + AIM')
    expect(skillAvailabilityLabel(['work', 'coding', 'aim'])).toBe('All modes')
  })
})
