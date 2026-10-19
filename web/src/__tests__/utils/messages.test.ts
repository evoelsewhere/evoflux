import { describe, expect, it } from 'vitest'

import { parseTeamBlocks } from '@/utils/messages'
import type { MessageResponse } from '@/api/types'

function assistantWithUiBlockCall(
  args: Record<string, unknown>,
  id = 'tc-1',
  msgId = 'm1',
): MessageResponse {
  return {
    id: msgId,
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

describe('parseTeamBlocks ui_block identity protocol (spec §1.4/§1.6)', () => {
  const V1 = [{ type: 'callout', tone: 'info', body: 'v1' }]
  const V2 = [{ type: 'callout', tone: 'info', body: 'v2' }]

  it('gives the group an identity-based id and uiBlockIdentity', () => {
    const blocks = parseTeamBlocks([
      assistantWithUiBlockCall({ blocks: V1, block_id: 'metrics' }),
    ])
    const group = blocks.find((b) => b.type === 'ui_block')

    expect(group?.uiBlockIdentity).toBe('metrics')
    expect(group?.id).toBe('m1:ui_block:metrics')
  })

  it('same-block_id from a later message upserts the group in place', () => {
    const blocks = parseTeamBlocks([
      assistantWithUiBlockCall(
        { blocks: V1, block_id: 'metrics', title: 'Metrics' },
        'tc-1',
        'm1',
      ),
      assistantWithUiBlockCall(
        { blocks: V2, block_id: 'metrics' },
        'tc-2',
        'm2',
      ),
    ])
    const groups = blocks.filter((b) => b.type === 'ui_block')

    expect(groups).toHaveLength(1)
    expect(groups[0].id).toBe('m1:ui_block:metrics') // position + id immutable
    expect(groups[0].uiBlockIdentity).toBe('metrics')
    expect(groups[0].uiBlocks).toEqual(V2)
    expect(groups[0].toolCallId).toBe('tc-2') // latest writer
    // The later call supplied no title — the original one survives.
    expect(groups[0].title).toBe('Metrics')
    // The group stays at the first call's position in the flat list.
    expect(blocks.indexOf(groups[0])).toBe(0)
  })

  it('unmatched replace_id appends with identity = replace_id', () => {
    const blocks = parseTeamBlocks([
      assistantWithUiBlockCall({ blocks: V1, replace_id: 'legacy' }),
    ])
    const group = blocks.find((b) => b.type === 'ui_block')

    expect(group?.uiBlockIdentity).toBe('legacy')
    expect(group?.id).toBe('m1:ui_block:legacy')
  })

  it("attaches the replaced call's tool result to the merged group", () => {
    const blocks = parseTeamBlocks([
      assistantWithUiBlockCall({ blocks: V1, block_id: 'metrics' }, 'tc-1', 'm1'),
      assistantWithUiBlockCall(
        { blocks: V2, replace_id: 'metrics' },
        'tc-2',
        'm2',
      ),
      {
        ...assistantWithUiBlockCall({}, 'tc-2', 'm3'),
        role: 'tool',
        tool_call_id: 'tc-2',
        content: 'Rendered 2 UI block(s)',
      },
    ])
    const groups = blocks.filter((b) => b.type === 'ui_block')

    expect(groups).toHaveLength(1)
    expect(groups[0].toolResult).toBe('Rendered 2 UI block(s)')
  })

  it('double-replay converges to a single group with final content', () => {
    const blocks = parseTeamBlocks([
      assistantWithUiBlockCall({ blocks: V1, block_id: 'metrics' }, 'tc-1', 'm1'),
      assistantWithUiBlockCall({ blocks: V1, block_id: 'metrics' }, 'tc-1', 'm1'),
      assistantWithUiBlockCall({ blocks: V2, replace_id: 'metrics' }, 'tc-2', 'm2'),
      assistantWithUiBlockCall({ blocks: V2, replace_id: 'metrics' }, 'tc-2', 'm2'),
    ])
    const groups = blocks.filter((b) => b.type === 'ui_block')

    expect(groups).toHaveLength(1)
    expect(groups[0].uiBlocks).toEqual(V2)
    expect(groups[0].uiBlockIdentity).toBe('metrics')
  })

  it("legacy no-field calls keep today's id, title and toolCallId", () => {
    const blocks = parseTeamBlocks([
      assistantWithUiBlockCall({ blocks: V1, title: 'Legacy' }),
    ])
    const group = blocks.find((b) => b.type === 'ui_block')

    expect(group?.id).toBe('m1:ui_block:tc-1')
    expect(group?.uiBlockIdentity).toBe('tc-1')
    expect(group?.toolCallId).toBe('tc-1')
    expect(group?.title).toBe('Legacy')
    expect(group?.uiBlocks).toEqual(V1)
  })
})
