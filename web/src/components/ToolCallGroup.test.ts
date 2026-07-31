import { describe, expect, it } from 'vitest'

import {
  groupConsecutiveToolCalls,
  type ToolBlockGroup,
} from './ToolCallGroup'
import type { ContentBlock } from '@/api/types'

function block(
  id: string,
  type: ContentBlock['type'],
  toolName?: string,
): ContentBlock {
  return {
    id,
    type,
    content: type === 'thinking' ? `reasoning ${id}` : '',
    toolName,
    toolDone: type === 'tool' ? true : undefined,
  }
}

describe('groupConsecutiveToolCalls', () => {
  it('keeps thinking inside one consecutive tool activity group', () => {
    const blocks = [
      block('thinking-1', 'thinking'),
      block('browser-1', 'tool', 'webbridge'),
      block('thinking-2', 'thinking'),
      block('browser-2', 'tool', 'webbridge'),
      block('browser-3', 'tool', 'webbridge'),
    ]

    const result = groupConsecutiveToolCalls(blocks)

    expect(result).toHaveLength(1)
    expect((result[0] as ToolBlockGroup).kind).toBe('group')
    expect((result[0] as ToolBlockGroup).toolName).toBe('webbridge')
    expect((result[0] as ToolBlockGroup).blocks).toEqual(blocks)
  })

  it('uses content blocks as boundaries between activity groups', () => {
    const answer = block('answer', 'text')
    const result = groupConsecutiveToolCalls([
      block('read-1', 'tool', 'read'),
      block('search-1', 'tool', 'grep'),
      answer,
      block('read-2', 'tool', 'read'),
    ])

    expect(result).toHaveLength(3)
    expect((result[0] as ToolBlockGroup).kind).toBe('group')
    expect(result[1]).toBe(answer)
    expect(result[2]).toMatchObject({ id: 'read-2', type: 'tool' })
  })
})
