import type { SkillMode } from '@/api/types'
import type { SkillAvailability } from '@/lib/skill-modes'

export function resolveRequestedSkillMode(mode: unknown): SkillMode | null {
  return mode === 'work' || mode === 'coding' ? mode : null
}

export function resolveSkillDetailMode({
  valid,
  modes,
  modeFilter,
  workspaceScoped,
}: {
  valid: boolean
  modes: readonly SkillMode[]
  modeFilter: 'all' | SkillAvailability
  workspaceScoped: boolean
}): SkillMode | null {
  // Mode-scoped runtime discovery excludes invalid candidates and may expose
  // a lower-precedence alternate. Keep invalid rows on the unscoped metadata
  // route so the exact row the user selected remains inspectable.
  if (!valid) return null
  if (modeFilter === 'work' || modeFilter === 'coding') return modeFilter
  if (modes.length === 1) return modes[0] ?? null
  return workspaceScoped ? 'coding' : null
}
