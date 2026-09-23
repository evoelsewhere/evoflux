/**
 * Display facts for a discovered Skill, shared by the Settings list and
 * editor. See ``documents/architecture/agent-skills.md``.
 */
import type { SkillSource, SkillSummary } from '@/api/types'

export const SKILL_SOURCE_LABEL: Record<SkillSource, string> = {
  project: 'Project',
  user: 'User',
  plugin: 'Plugin',
  builtin: 'Built-in',
}

type SkillFactInput = Pick<
  SkillSummary,
  | 'enabled'
  | 'model_invocable'
  | 'user_invocable'
  | 'valid'
  | 'diagnostics'
  | 'shadowed_paths'
  | 'editable'
  | 'symlinked'
  | 'resource_count'
>

/** Short status labels, most important first. */
export function skillStatusLabels(skill: SkillFactInput): string[] {
  const labels: string[] = []
  if (!skill.enabled) labels.push('Disabled')
  if (!skill.valid) labels.push('Invalid')
  if (!skill.model_invocable) labels.push('Hidden from model')
  if (!skill.user_invocable) labels.push('Not user-invocable')
  if (skill.diagnostics.length > 0) {
    const count = skill.diagnostics.length
    labels.push(`${count} diagnostic${count === 1 ? '' : 's'}`)
  }
  if (skill.shadowed_paths.length > 0) {
    const count = skill.shadowed_paths.length
    labels.push(`Shadows ${count} other skill${count === 1 ? '' : 's'}`)
  }
  if (skill.resource_count > 0) {
    const count = skill.resource_count
    labels.push(`${count} file${count === 1 ? '' : 's'}`)
  }
  if (skill.symlinked) labels.push('Symlink')
  if (!skill.editable) labels.push('Read-only')
  return labels
}

/** The first error diagnostic, used as the reason an invalid Skill is not loaded. */
export function skillInvalidReason(skill: Pick<SkillSummary, 'valid' | 'diagnostics'>): string | undefined {
  if (skill.valid) return undefined
  const error = skill.diagnostics.find((diagnostic) => diagnostic.severity === 'error')
  return error?.message ?? 'Invalid SKILL.md'
}
