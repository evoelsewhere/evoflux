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
  it('is labelled with the product name, not the methodology', () => {
    // The rail is narrow and the tab sits next to Files and Terminal, so it
    // carries the product name. The methodology is spelled out in the panel.
    expect(WORKBENCH_TOOLS.easd.label).toBe('Evo Agent Specs')
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
