import { describe, expect, it } from 'vitest'

import type { MessageResponse } from '@/api/types'
import { sumUsageFromMessages } from '@/utils/messages'

function assistantMessage(content: string | null): MessageResponse {
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
    extra: null,
    created_at: '2026-08-14T08:00:00Z',
    attachments: null,
  }
}

describe('turn usage history restoration', () => {
  it('restores current context and aggregate turn usage independently', () => {
    const message = assistantMessage('Done')
    message.extra = {
      usage: { input: 14_200, output: 17, cache: 2_000 },
      turn_usage: {
        input: 17_000,
        output: 29,
        cache: 2_500,
        calls: 3,
        phases: {
          main: { input: 14_200, output: 17, cache: 2_000, calls: 1 },
          title: { input: 2_800, output: 12, cache: 500, calls: 1 },
        },
      },
    }

    expect(sumUsageFromMessages([message])).toMatchObject({
      promptTokens: 14_200,
      completionTokens: 17,
      cachedTokens: 2_000,
      turnPromptTokens: 17_000,
      turnCompletionTokens: 29,
      turnTotalTokens: 17_029,
      turnCachedTokens: 2_500,
      turnCalls: 3,
      turnPhases: {
        main: { input: 14_200, output: 17, cache: 2_000, calls: 1 },
      },
    })
  })
})
