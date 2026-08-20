import { describe, expect, it } from 'vitest'

import type { MessageResponse } from '@/api/types'
import { parseApiMessages, parseTeamBlocks } from '@/utils/messages'

function lifecycleMessage(content: string | null): MessageResponse {
  return {
    id: 'message-1',
    session_id: 'session-1',
    role: 'assistant',
    content,
    reasoning_content: null,
    tool_calls: null,
    tool_call_id: null,
    name: 'lead',
    is_summary: false,
    is_hidden: false,
    extra: { lifecycle: 'sleep' },
    created_at: '2026-08-14T08:00:00Z',
    attachments: null,
  }
}

describe('sleep lifecycle message parsing', () => {
  it('keeps lifecycle metadata without manufacturing sentinel content', () => {
    const apiBlocks = parseApiMessages([lifecycleMessage(null)])[0]?.blocks
    const teamBlocks = parseTeamBlocks([lifecycleMessage(null)])

    expect(apiBlocks).toHaveLength(1)
    expect(apiBlocks?.[0]).toMatchObject({
      type: 'text',
      content: '',
      extra: { lifecycle: 'sleep' },
    })
    expect(teamBlocks).toHaveLength(1)
    expect(teamBlocks[0]).toMatchObject({
      type: 'text',
      content: '',
      extra: { lifecycle: 'sleep' },
    })
  })

  it('preserves visible text that precedes the lifecycle transition', () => {
    const blocks = parseTeamBlocks([lifecycleMessage('Work is underway.')])

    expect(blocks[0]).toMatchObject({
      content: 'Work is underway.',
      extra: { lifecycle: 'sleep' },
    })
  })

  it('uses stable block identities when durable history is parsed again', () => {
    const first = parseTeamBlocks([lifecycleMessage('Work is underway.')])
    const second = parseTeamBlocks([lifecycleMessage('Work is underway.')])

    expect(first[0]?.id).toBe('message-1:text')
    expect(second[0]?.id).toBe(first[0]?.id)
  })
})
