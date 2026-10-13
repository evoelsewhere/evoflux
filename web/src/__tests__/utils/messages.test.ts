import { describe, expect, it } from 'vitest'

import { parseTeamBlocks } from '@/utils/messages'
import type { MessageResponse } from '@/api/types'

function assistantWithUiBlockCall(
  args: Record<string, unknown>,
  id = 'tc-1',
): MessageResponse {
  return {
    id: 'm1',
    session_id: 's1',
    role: 'assistant',
    content: null,
    reasoning_content: null,
    tool_calls: [
      {
        id,
        type: 'function',
        function: { name: 'ui_block', arguments: JSON.stringify(args) },
      },
    ],
    tool_call_id: null,
    name: 'lead',
    is_summary: false,
    is_hidden: false,
    extra: null,
    created_at: '2026-10-13T10:00:00Z',
    attachments: null,
  }
}

describe('parseTeamBlocks ui_block reconstruction (Feature C, §6.1)', () => {
  it('reconstructs the ui_block block from persisted tool arguments', () => {
    const msgs = [
      assistantWithUiBlockCall({
        blocks: [
          { type: 'stat_cards', cards: [{ label: 'CPU', value: 42 }] },
          { type: 'progress', label: 'Upload', value: 1, max: 4 },
        ],
        title: 'metrics',
      }),
    ]
    const blocks = parseTeamBlocks(msgs)
    const uiBlocks = blocks.filter((b) => b.type === 'ui_block')
    expect(uiBlocks).toHaveLength(1)
    expect(uiBlocks[0].toolCallId).toBe('tc-1')
    expect(uiBlocks[0].title).toBe('metrics')
    expect(uiBlocks[0].uiBlocks).toHaveLength(2)
    expect(uiBlocks[0].uiBlocks?.[0]).toEqual({
      type: 'stat_cards',
      cards: [{ label: 'CPU', value: 42 }],
    })
    // No generic tool chip — the widget precedent (mirror :236-238).
    expect(blocks.some((b) => b.type === 'tool' && b.toolName === 'ui_block')).toBe(false)
  })

  it('falls back to the default title when the call has none', () => {
    const blocks = parseTeamBlocks([
      assistantWithUiBlockCall({
        blocks: [{ type: 'callout', tone: 'success', body: 'done' }],
      }),
    ])
    const uiBlock = blocks.find((b) => b.type === 'ui_block')
    expect(uiBlock?.title).toBe('UI Block')
  })

  it('does not duplicate the block on a second pass', () => {
    const msgs = [
      assistantWithUiBlockCall({
        blocks: [{ type: 'key_value', pairs: [{ version: '3.0.6' }] }],
      }),
    ]
    const first = parseTeamBlocks(msgs)
    const second = parseTeamBlocks(msgs)
    expect(second).toEqual(first)
    expect(second.filter((b) => b.type === 'ui_block')).toHaveLength(1)
  })

  it('falls back to a tool chip when args carry no blocks array', () => {
    const blocks = parseTeamBlocks([assistantWithUiBlockCall({ nope: true })])
    expect(blocks.some((b) => b.type === 'ui_block')).toBe(false)
    expect(blocks.some((b) => b.type === 'tool' && b.toolName === 'ui_block')).toBe(true)
  })
})
