import { describe, expect, it } from 'vitest'

import type { ContentBlock } from '@/api/types'
import { getVisibleTurnWindow, partitionTurns } from '@/utils/turns'

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
})
