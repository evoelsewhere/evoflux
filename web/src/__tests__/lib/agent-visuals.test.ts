import { describe, expect, it } from 'vitest'

import {
  agentDisplayName,
  agentTeamFromName,
  isBuiltInAgentName,
} from '@/lib/agent-visuals'

describe('agent settings visuals', () => {
  it('maps agent paths to their team and display name', () => {
    expect(agentTeamFromName('evoflux')).toBe('forge')
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
})
