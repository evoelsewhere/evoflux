import { describe, expect, it } from 'vitest'

import {
  SKILL_SOURCE_LABEL,
  skillInvalidReason,
  skillStatusLabels,
} from '@/components/settings/skillFacts'

const base = {
  enabled: true,
  model_invocable: true,
  user_invocable: true,
  valid: true,
  diagnostics: [],
  shadowed_paths: [],
  editable: true,
  symlinked: false,
  resource_count: 0,
}

describe('skill list facts', () => {
  it('shows nothing extra for an enabled, editable, valid skill', () => {
    expect(skillStatusLabels(base)).toEqual([])
  })

  it('labels disabled, hidden, not-invocable, shadowing, and read-only skills', () => {
    expect(
      skillStatusLabels({
        ...base,
        enabled: false,
        model_invocable: false,
        user_invocable: false,
        shadowed_paths: ['/home/u/.claude/skills/pdf/SKILL.md'],
        editable: false,
        resource_count: 2,
      }),
    ).toEqual([
      'Disabled',
      'Hidden from model',
      'Not user-invocable',
      'Shadows 1 other skill',
      '2 files',
      'Read-only',
    ])
  })

  it('counts diagnostics and uses the first error as the invalid reason', () => {
    const invalid = {
      ...base,
      valid: false,
      diagnostics: [
        { code: 'unknown-field', message: 'Unknown field foo.', severity: 'warning' as const },
        { code: 'missing-description', message: 'Frontmatter requires a description.', severity: 'error' as const },
      ],
    }
    expect(skillStatusLabels(invalid)).toEqual(['Invalid', '2 diagnostics'])
    expect(skillInvalidReason(invalid)).toBe('Frontmatter requires a description.')
    expect(skillInvalidReason(base)).toBeUndefined()
  })

  it('names every source', () => {
    expect(SKILL_SOURCE_LABEL).toEqual({
      project: 'Project',
      user: 'User',
      plugin: 'Plugin',
      builtin: 'Built-in',
    })
  })
})
