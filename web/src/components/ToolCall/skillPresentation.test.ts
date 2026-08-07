import { describe, expect, it } from 'vitest'

import { getSkillCallPresentation } from './skillPresentation'

describe('getSkillCallPresentation', () => {
  it('labels activation separately from resource access', () => {
    expect(getSkillCallPresentation(JSON.stringify({
      action: 'load',
      skill_name: 'coding-investigation',
    }))).toMatchObject({
      completedLabel: 'Loaded skill',
      headerTitle: 'coding-investigation',
      family: 'skill-load',
    })

    expect(getSkillCallPresentation(JSON.stringify({
      action: 'read_resource',
      skill_name: 'coding-investigation',
      resource_path: 'references/code-graph-contract.md',
    }))).toMatchObject({
      completedLabel: 'Read skill resource',
      headerTitle: 'coding-investigation · references/code-graph-contract.md',
      family: 'skill-resource',
    })
  })

  it('treats omitted action with a skill name as the default load action', () => {
    expect(getSkillCallPresentation(JSON.stringify({
      skill_name: 'pdf',
    }))).toMatchObject({
      kind: 'load',
      completedLabel: 'Loaded skill',
    })
  })

  it('labels catalog listing without inventing a skill name', () => {
    expect(getSkillCallPresentation(JSON.stringify({ action: 'list' }))).toEqual({
      kind: 'list',
      completedLabel: 'Listed skills',
      activityLabel: 'Listing skills',
      headerTitle: null,
      family: 'skill-list',
    })
  })
})
