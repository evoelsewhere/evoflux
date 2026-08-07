import { describe, expect, it } from 'vitest'

import {
  skillDescriptionSchema,
  validateNewSkillDraft,
  validateSkillDraft,
} from '@/components/settings/schema'

describe('skill description schema', () => {
  it('accepts portable Agent Skills descriptions up to 1024 characters', () => {
    expect(skillDescriptionSchema.safeParse('x'.repeat(1024)).success).toBe(true)
    expect(skillDescriptionSchema.safeParse('x'.repeat(1025)).success).toBe(false)
  })
})

describe('new skill package naming', () => {
  const draft = (name: string) =>
    `---\nname: ${name}\ndescription: Focused workflow\n---\n\n# Skill\n`

  it('requires portable lowercase-hyphen names for newly scaffolded packages', () => {
    expect(validateNewSkillDraft(draft('code-review'))).toBeNull()
    expect(validateNewSkillDraft(draft('a'.repeat(64)))).toBeNull()
    expect(validateNewSkillDraft(draft('Legacy_Name'))?.name).toContain('lowercase')
    expect(validateNewSkillDraft(draft('git/commit'))?.name).toContain('lowercase')
    expect(validateNewSkillDraft(draft('a'.repeat(65)))?.name).toBe('Max 64 characters')
  })

  it('keeps legacy and nested imported skill names editable', () => {
    expect(validateSkillDraft(draft('Legacy_Name'))).toBeNull()
    expect(validateSkillDraft(draft('git/commit'))).toBeNull()
  })
})
