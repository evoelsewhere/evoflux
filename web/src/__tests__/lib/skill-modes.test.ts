import { describe, expect, it } from 'vitest'

import {
  availabilityFromModes,
  modesFromAvailability,
  skillAvailabilityLabel,
} from '@/lib/skill-modes'

describe('skill mode helpers', () => {
  it('maps the UI choices to canonical API modes', () => {
    expect(modesFromAvailability('work')).toEqual(['work'])
    expect(modesFromAvailability('coding')).toEqual(['coding'])
    expect(modesFromAvailability('both')).toEqual(['work', 'coding'])
  })

  it('defaults missing or shared modes to both', () => {
    expect(availabilityFromModes()).toBe('both')
    expect(availabilityFromModes(['work', 'coding'])).toBe('both')
  })

  it('renders explicit management labels', () => {
    expect(skillAvailabilityLabel(['work'])).toBe('Work only')
    expect(skillAvailabilityLabel(['coding'])).toBe('Coding only')
    expect(skillAvailabilityLabel(['work', 'coding'])).toBe('Work + Coding')
  })
})
