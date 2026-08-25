import { describe, expect, it } from 'vitest'

import { isWorkbenchToolEnabled, WORKBENCH_TOOLS } from '@/components/workbench/tools'

describe('workspace overview workbench tool', () => {
  it('is available for coding workspaces', () => {
    expect(isWorkbenchToolEnabled('overview', {
      mode: 'coding',
      sessionId: 'session-1',
      workspace: '/repo',
    })).toBe(true)
  })

  it('does not appear without a coding workspace', () => {
    expect(isWorkbenchToolEnabled('overview', {
      mode: 'coding',
      sessionId: null,
      workspace: null,
    })).toBe(false)
    expect(isWorkbenchToolEnabled('overview', {
      mode: 'work',
      sessionId: 'session-1',
      workspace: null,
    })).toBe(false)
  })
})

describe('process manager workbench tool', () => {
  it('is available even before a session is selected', () => {
    expect(isWorkbenchToolEnabled('processes', {
      mode: 'work',
      sessionId: null,
      workspace: null,
    })).toBe(true)
  })
})

describe('Evo Agent Specs workbench tool', () => {
  it('uses the full methodology name in the UI', () => {
    expect(WORKBENCH_TOOLS.easd.label).toBe('Agent Specification-Driven Development')
  })

  it('is available only in a Coding workspace', () => {
    expect(isWorkbenchToolEnabled('easd', {
      mode: 'coding',
      sessionId: 'session-1',
      workspace: '/repo',
    })).toBe(true)
    expect(isWorkbenchToolEnabled('easd', {
      mode: 'coding',
      sessionId: 'session-1',
      workspace: null,
    })).toBe(false)
    expect(isWorkbenchToolEnabled('easd', {
      mode: 'work',
      sessionId: 'session-1',
      workspace: '/repo',
    })).toBe(false)
  })
})
