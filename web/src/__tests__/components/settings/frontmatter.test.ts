import { describe, expect, it } from 'vitest'

import {
  combinePreservingUnknown,
  splitFrontmatter,
  type AgentFrontmatter,
} from '@/components/settings/frontmatter'

describe('agent frontmatter round trip', () => {
  it('preserves unknown YAML and comments while updating form fields', () => {
    const original = `---
# keep this comment
name: explorer
role: member
model: old:model
responses_api: true
custom_hook:
  enabled: true
---

Original instructions.
`
    const next: AgentFrontmatter = {
      name: 'explorer',
      role: 'member',
      model: 'new:model',
      responses_api: true,
      tools_opt_out: ['shell'],
    }

    const result = combinePreservingUnknown(original, next, 'Updated instructions.')
    const parsed = splitFrontmatter(result)

    expect(parsed.fm).toContain('# keep this comment')
    expect(parsed.fm).toContain('custom_hook:\n  enabled: true')
    expect(parsed.fm).toContain('model: new:model')
    expect(parsed.fm).toContain('responses_api: true')
    expect(parsed.fm).toContain('tools_opt_out:\n  - shell')
    expect(parsed.body.trim()).toBe('Updated instructions.')
  })

  it('serializes member ownership and omits it from a lead config', () => {
    const member = combinePreservingUnknown(
      '---\nname: coder\nrole: member\n---\n\nCode.\n',
      { name: 'coder', role: 'member', lead: 'engineering' },
      'Code.',
    )
    const lead = combinePreservingUnknown(
      member,
      { name: 'coder', role: 'lead', lead: null },
      'Lead.',
    )

    expect(splitFrontmatter(member).fm).toContain('lead: engineering')
    expect(splitFrontmatter(lead).fm).not.toContain('lead:')
  })
})
