import { describe, expect, it } from 'vitest'
import { parseApiMessages, parseTeamBlocks } from './messages'
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

describe('compaction transcript privacy', () => {
  const summary = userMessage({
    id: 'summary-1',
    content: 'private compacted context',
    is_summary: true,
  })

  it('hydrates team history as a content-free status marker', () => {
    const [block] = parseTeamBlocks([summary])

    expect(block.type).toBe('compaction')
    expect(block.content).toBe('')
    expect(block.extra).toEqual({ state: 'compacted' })
  })

  it('hydrates single-agent history as a content-free status marker', () => {
    const [message] = parseApiMessages([summary])

    expect(message.blocks[0].type).toBe('compaction')
    expect(message.blocks[0].content).toBe('')
    expect(message.blocks[0].extra).toEqual({ state: 'compacted' })
  })
})

describe('Claude imported transcript structure', () => {
  it('pairs a tool-only assistant turn with its result and retains sidechain origin', () => {
    const blocks = parseTeamBlocks([
      userMessage({
        id: 'task-call',
        role: 'assistant',
        content: '',
        tool_calls: [{
          id: 'call-1',
          type: 'function',
          function: { name: 'Task', arguments: '{"description":"Inspect"}' },
        }],
        extra: { import_source: { provider: 'claude_code', event_id: 'assistant-1' } },
      }),
      userMessage({
        id: 'subagent-output',
        role: 'assistant',
        content: 'Found the cause.',
        name: 'reviewer',
        extra: { import_source: { provider: 'claude_code', is_sidechain: true, agent_id: 'reviewer' } },
      }),
      userMessage({
        id: 'tool-result',
        role: 'tool',
        content: 'Review is complete.',
        tool_call_id: 'call-1',
        extra: { import_source: { provider: 'claude_code', event_kind: 'tool_result' } },
      }),
    ])

    expect(blocks.find((block) => block.type === 'tool')).toMatchObject({
      toolName: 'Task',
      toolDone: true,
      toolResult: 'Review is complete.',
      toolCallId: 'call-1',
    })
    expect(blocks.find((block) => block.content === 'Found the cause.')).toMatchObject({
      extra: {
        import_source: { is_sidechain: true, agent_id: 'reviewer' },
      },
    })
  })

  it('renders multiple tool calls and their results when the parent has no text response', () => {
    const blocks = parseTeamBlocks([
      userMessage({
        id: 'user-multi',
        content: 'Run two independent checks.',
      }),
      userMessage({
        id: 'parent-multi',
        role: 'assistant',
        content: '',
        tool_calls: [
          {
            id: 'task-reviewer',
            type: 'function',
            function: { name: 'Task', arguments: '{"subagent_type":"reviewer"}' },
          },
          {
            id: 'task-explorer',
            type: 'function',
            function: { name: 'Task', arguments: '{"subagent_type":"explorer"}' },
          },
        ],
      }),
      userMessage({
        id: 'reviewer-result',
        role: 'tool',
        content: 'Reviewer complete.',
        tool_call_id: 'task-reviewer',
      }),
      userMessage({
        id: 'explorer-result',
        role: 'tool',
        content: 'Explorer complete.',
        tool_call_id: 'task-explorer',
      }),
    ])

    expect(blocks.filter((block) => block.type === 'tool')).toMatchObject([
      { toolName: 'Task', toolCallId: 'task-reviewer', toolDone: true, toolResult: 'Reviewer complete.' },
      { toolName: 'Task', toolCallId: 'task-explorer', toolDone: true, toolResult: 'Explorer complete.' },
    ])
    expect(blocks.filter((block) => block.type === 'text')).toEqual([])
    expect(blocks.find((block) => block.type === 'user')?.content).toBe(
      'Run two independent checks.',
    )
  })
})
