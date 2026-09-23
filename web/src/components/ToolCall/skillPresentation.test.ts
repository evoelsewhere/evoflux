import { describe, expect, it } from 'vitest'

import { getSkillActivationName, getSkillCallPresentation } from './skillPresentation'

const read = (args: Record<string, unknown>) => JSON.stringify(args)

describe('getSkillCallPresentation', () => {
  it('presents a full read of SKILL.md as a skill activation', () => {
    expect(
      getSkillCallPresentation('read', read({ path: '/home/u/.evoflux/skills/pdf/SKILL.md' })),
    ).toEqual({
      skillName: 'pdf',
      completedLabel: 'Used skill',
      activityLabel: 'Using skill pdf',
      headerTitle: 'pdf',
      family: 'skill',
    })
  })

  it('accepts Windows paths and an explicit offset of 1', () => {
    expect(
      getSkillActivationName(
        'read',
        read({ path: 'C:\\Users\\me\\.claude\\skills\\code-review\\SKILL.md', offset: 1 }),
      ),
    ).toBe('code-review')
    expect(
      getSkillActivationName('read', read({ path: '/s/pdf/SKILL.md', offset: null, limit: null })),
    ).toBe('pdf')
  })

  it('ignores partial reads, other files, and other tools', () => {
    expect(getSkillActivationName('read', read({ path: '/s/pdf/SKILL.md', offset: 40 }))).toBeNull()
    expect(getSkillActivationName('read', read({ path: '/s/pdf/SKILL.md', limit: 20 }))).toBeNull()
    expect(getSkillActivationName('read', read({ path: '/s/pdf/reference.md' }))).toBeNull()
    expect(getSkillActivationName('read', read({ path: 'SKILL.md' }))).toBeNull()
    expect(getSkillActivationName('read', read({ path: '/s/pdf/skill.md' }))).toBeNull()
    expect(getSkillActivationName('write', read({ path: '/s/pdf/SKILL.md' }))).toBeNull()
    expect(getSkillActivationName('skill', read({ skill_name: 'pdf' }))).toBeNull()
    expect(getSkillActivationName('read', 'not json')).toBeNull()
    expect(getSkillActivationName('read', undefined)).toBeNull()
  })
})
