import { describe, expect, it } from 'vitest'

import { isWorkbenchToolEnabled } from '@/components/workbench/tools'

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
      mode: 'forge',
      sessionId: 'session-1',
      workspace: null,
    })).toBe(false)
  })
})
