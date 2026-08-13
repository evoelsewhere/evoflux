import { describe, expect, it } from 'vitest'

import { shouldShowPendingActivity } from '@/utils/transcript-layout'
import type { ContentBlock } from '@/api/types'

function userBlock(id: string, fromAgent?: string): ContentBlock {
  return {
    id,
    type: 'user',
    content: fromAgent === 'system'
      ? '[system]: You are still waiting on a team_handoff from explorer#1.'
      : 'Research gold prices',
    extra: fromAgent ? { from_agent: fromAgent } : undefined,
  }
}

describe('shouldShowPendingActivity', () => {
  it('shows a runway for a direct user prompt before agent output arrives', () => {
    expect(shouldShowPendingActivity({
      currentBlocks: [userBlock('user')],
      isContinuing: false,
      isError: false,
      isWorking: true,
    })).toBe(true)
  })

  it('does not turn an internal delegation wait message into a second runway', () => {
    expect(shouldShowPendingActivity({
      currentBlocks: [userBlock('wait', 'system')],
      isContinuing: false,
      isError: false,
      isWorking: true,
    })).toBe(false)
  })

  it('keeps the explicit continue gap visible without current blocks', () => {
    expect(shouldShowPendingActivity({
      currentBlocks: [],
      isContinuing: true,
      isError: false,
      isWorking: true,
    })).toBe(true)
  })
})
