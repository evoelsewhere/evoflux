import type { SkillMode } from '@/api/types'

export type SkillAvailability = SkillMode | 'both'

export function availabilityFromModes(modes?: SkillMode[]): SkillAvailability {
  if (modes?.length === 1) return modes[0]
  return 'both'
}

export function modesFromAvailability(availability: SkillAvailability): SkillMode[] {
  return availability === 'both' ? ['work', 'coding'] : [availability]
}

export function skillAvailabilityLabel(modes?: SkillMode[]): string {
  const availability = availabilityFromModes(modes)
  if (availability === 'work') return 'Work only'
  if (availability === 'coding') return 'Coding only'
  return 'Work + Coding'
}
