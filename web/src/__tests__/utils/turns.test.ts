import { describe, expect, it } from 'vitest'

import type { ContentBlock } from '@/api/types'
import { getVisibleTurnWindow, isLatestStreamingItem, partitionTurns } from '@/utils/turns'

const block = (type: ContentBlock['type'], content: string): ContentBlock =>
  ({ type, content, id: `${type}-${content}` }) as ContentBlock

describe('turn partitioning', () => {
  it('groups contiguous assistant blocks around user messages', () => {
    const turns = partitionTurns([
      block('thinking', 'plan'),
      block('tool', 'read'),
      block('text', 'answer'),
      block('user', 'next'),
      block('text', 'response'),
    ])

    expect(turns).toHaveLength(3)
    expect(turns[0]).toMatchObject({
      kind: 'assistant',
      startIndex: 0,
    })
    expect(turns[1]).toMatchObject({
      kind: 'user',
      index: 3,
    })
    expect(turns[2]).toMatchObject({
      kind: 'assistant',
      startIndex: 4,
    })
  })

  it('returns only the newest requested turns', () => {
    const turns = partitionTurns([
      block('text', 'one'),
      block('user', 'two'),
      block('text', 'three'),
    ])

    const window = getVisibleTurnWindow(turns, 2)
    expect(window.hiddenTurnCount).toBe(1)
    expect(window.visibleTurnItems).toEqual(turns.slice(1))
  })

  it('marks only the newest item in a live turn as streaming', () => {
    expect(isLatestStreamingItem(true, 0, 3)).toBe(false)
    expect(isLatestStreamingItem(true, 1, 3)).toBe(false)
    expect(isLatestStreamingItem(true, 2, 3)).toBe(true)
    expect(isLatestStreamingItem(false, 2, 3)).toBe(false)
  })

  it('folds delegation transport into the surrounding assistant lifecycle', () => {
    const handoff: ContentBlock = {
      ...block('user', 'handoff'),
      extra: {
        from_agent: 'explorer#1',
        _handoff_artifact: {
          task_id: '0198a1d2-3456-7890-abcd-ef0123456789',
          status: 'final',
          summary: 'Done.',
        },
      },
    }
    const waitNudge: ContentBlock = {
      ...block('user', 'You are still waiting on a team_handoff from explorer#1.'),
      extra: { from_agent: 'system' },
    }

    const delegationBlock: ContentBlock = {
      ...block('tool', 'delegate'),
      toolName: 'team_delegate',
    }

    const turns = partitionTurns([
      delegationBlock,
      waitNudge,
      block('text', '<sleep>'),
      handoff,
      block('text', 'Final synthesis.'),
    ])

    expect(turns).toHaveLength(1)
    expect(turns[0]).toMatchObject({ kind: 'assistant' })
    if (turns[0]?.kind === 'assistant') {
      expect(turns[0].blocks.map((item) => item.content)).toEqual([
        'delegate',
        'Final synthesis.',
      ])
    }
  })
})
