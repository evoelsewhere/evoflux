import { describe, expect, it } from 'vitest'

import {
  agentDisplayName,
  agentTeamFromName,
  agentVisualKind,
  isBuiltInAgentName,
} from '@/lib/agent-visuals'

describe('agent settings visuals', () => {
  it('maps agent paths to their team and display name', () => {
    expect(agentTeamFromName('evoflux')).toBe('work')
    expect(agentTeamFromName('coding/coder')).toBe('coding')
    expect(agentTeamFromName('aim/aim-appraiser')).toBe('aim')
    expect(agentDisplayName('coding/coder')).toBe('coder')
  })

  it('recognizes lowercase built-in leads', () => {
    expect(isBuiltInAgentName('evoflux', 'lead')).toBe(true)
    expect(isBuiltInAgentName('coding/evoflux', 'lead')).toBe(true)
    expect(isBuiltInAgentName('aim/aim-lead', 'lead')).toBe(true)
  })

  it('does not protect custom agents that merely share a team directory', () => {
    expect(isBuiltInAgentName('coding/custom-reviewer', 'member')).toBe(false)
    expect(isBuiltInAgentName('aim/aim-custom', 'member')).toBe(false)
  })

  it('resolves settings paths and live handles to specialized emblems', () => {
    expect(agentVisualKind('coding/coder')).toBe('coder')
    expect(agentVisualKind('architect#2')).toBe('architect')
    expect(agentVisualKind('debate#3')).toBe('debate')
    expect(agentVisualKind('explorer#1')).toBe('explorer')
  })

  it('uses the lead and custom emblems when appropriate', () => {
    expect(agentVisualKind('anything', 'lead')).toBe('EvoFlux')
    expect(agentVisualKind('custom-reviewer')).toBe('custom')
  })
})
