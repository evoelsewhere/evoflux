import { describe, expect, it } from 'vitest'
import { parseTeamBlocks } from './messages'
import type { MessageResponse } from '@/api/types'

function userMessage(overrides: Partial<MessageResponse> = {}): MessageResponse {
  return {
    id: 'message-1',
    session_id: 'session-1',
    role: 'user',
    content: '[Untrusted browser selection]\nUser request:\nExplain this',
    reasoning_content: null,
    tool_calls: null,
    tool_call_id: null,
    name: null,
    is_summary: false,
    is_hidden: false,
    extra: null,
    created_at: '2026-08-01T00:00:00Z',
    attachments: null,
    ...overrides,
  }
}

describe('WebBridge transcript parity', () => {
  it('renders the original Side Chat request in EvoFlux while preserving metadata', () => {
    const [block] = parseTeamBlocks([
      userMessage({
        extra: {
          webbridge_side_panel: {
            user_content: 'Explain this',
            contexts: [{ type: 'selection', page_url: 'https://example.com/page' }],
          },
        },
      }),
    ])

    expect(block.content).toBe('Explain this')
    expect(block.extra?.webbridge_side_panel).toEqual({
      user_content: 'Explain this',
      contexts: [{ type: 'selection', page_url: 'https://example.com/page' }],
    })
  })

  it('keeps legacy WebBridge rows readable when display metadata is absent', () => {
    const [block] = parseTeamBlocks([userMessage()])
    expect(block.content).toContain('User request:\nExplain this')
  })
})
