import type { SkillMode } from '@/api/types'

export const ALL_SKILL_MODES: readonly SkillMode[] = ['work', 'coding', 'aim']

export type SkillModeFilter = 'all' | SkillMode | 'all-modes'

export function normalizeSkillModes(modes?: readonly SkillMode[]): SkillMode[] {
  if (!modes?.length) return [...ALL_SKILL_MODES]
  const selected = new Set(modes)
  const normalized = ALL_SKILL_MODES.filter((mode) => selected.has(mode))
  return normalized.length > 0 ? normalized : [...ALL_SKILL_MODES]
}

export function skillModesEqual(
  left?: readonly SkillMode[],
  right?: readonly SkillMode[],
): boolean {
  const normalizedLeft = normalizeSkillModes(left)
  const normalizedRight = normalizeSkillModes(right)
  return normalizedLeft.length === normalizedRight.length &&
    normalizedLeft.every((mode, index) => mode === normalizedRight[index])
}

export function hasAllSkillModes(modes?: readonly SkillMode[]): boolean {
  return normalizeSkillModes(modes).length === ALL_SKILL_MODES.length
}

export function skillAvailabilityLabel(modes?: readonly SkillMode[]): string {
  const normalized = normalizeSkillModes(modes)
  if (normalized.length === ALL_SKILL_MODES.length) return 'All modes'
  if (normalized.length === 1) {
    if (normalized[0] === 'work') return 'Work only'
    if (normalized[0] === 'coding') return 'Coding only'
    return 'AIM only'
  }
  if (normalized.includes('work') && normalized.includes('coding')) return 'Work + Coding'
  if (normalized.includes('work') && normalized.includes('aim')) return 'Work + AIM'
  return 'Coding + AIM'
}
