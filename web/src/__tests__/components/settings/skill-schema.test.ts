import { describe, expect, it } from 'vitest'

import {
  skillDescriptionSchema,
  skillDraftName,
  validateSkillDraft,
  validateSkillName,
} from '@/components/settings/schema'

describe('skill description schema', () => {
  it('accepts descriptions up to 1024 characters', () => {
    expect(skillDescriptionSchema.safeParse('x'.repeat(1024)).success).toBe(true)
    expect(skillDescriptionSchema.safeParse('x'.repeat(1025)).success).toBe(false)
  })

  it('rejects empty descriptions and XML tags', () => {
    expect(skillDescriptionSchema.safeParse('   ').success).toBe(false)
    expect(skillDescriptionSchema.safeParse('Reads <file> contents.').success).toBe(false)
    expect(skillDescriptionSchema.safeParse('Flags values where x < 3 or y > 5.').success).toBe(true)
  })
})

describe('skill name rules', () => {
  it('accepts flat lowercase-hyphen names up to 64 characters', () => {
    expect(validateSkillName('code-review')).toBeNull()
    expect(validateSkillName('pdf2')).toBeNull()
    expect(validateSkillName('a'.repeat(64))).toBeNull()
  })

  it('rejects nested, uppercase, underscore, and malformed hyphen names', () => {
    for (const name of ['git/commit', 'Legacy_Name', 'Code-Review', '-lead', 'trail-', 'a--b']) {
      expect(validateSkillName(name)).toContain('lowercase')
    }
    expect(validateSkillName('a'.repeat(65))).toBe('Max 64 characters')
  })

  it('rejects reserved words', () => {
    expect(validateSkillName('claude-helper')).toContain('anthropic')
    expect(validateSkillName('my-anthropic-tools')).toContain('claude')
  })
})

describe('skill draft validation', () => {
  const draft = (name: string, description = 'Reviews code. Use when asked for a review.') =>
    `---\nname: ${name}\ndescription: ${description}\n---\n\n# Skill\n\nDo the work.\n`

  it('accepts a spec-compliant SKILL.md', () => {
    expect(validateSkillDraft(draft('code-review'))).toBeNull()
  })

  it('reports name and description errors by field', () => {
    expect(validateSkillDraft(draft('git/commit'))?.name).toContain('lowercase')
    expect(validateSkillDraft(draft('code-review', ''))?.description).toBeDefined()
  })

  it('requires the name to match the existing skill folder when editing', () => {
    expect(validateSkillDraft(draft('code-review'), { expectedName: 'code-review' })).toBeNull()
    expect(validateSkillDraft(draft('renamed'), { expectedName: 'code-review' })?.name).toContain(
      'code-review',
    )
  })

  it('requires frontmatter and a body', () => {
    expect(validateSkillDraft('# no frontmatter')?._root).toContain('frontmatter')
    expect(
      validateSkillDraft('---\nname: empty\ndescription: Does nothing.\n---\n')?.body,
    ).toBeDefined()
  })

  it('checks folded multi-line descriptions', () => {
    const folded = `---\nname: long\ndescription: >\n  ${'x'.repeat(600)}\n  ${'y'.repeat(600)}\n---\n\nBody\n`
    expect(validateSkillDraft(folded)?.description).toBe('Max 1024 characters')
    const short = '---\nname: short\ndescription: >-\n  Reads files.\n  Use when asked.\n---\n\nBody\n'
    expect(validateSkillDraft(short)).toBeNull()
  })

  it('reads the frontmatter name', () => {
    expect(skillDraftName(draft('pdf-tools'))).toBe('pdf-tools')
    expect(skillDraftName('no frontmatter')).toBeNull()
  })
})
