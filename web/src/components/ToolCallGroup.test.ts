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
  it('groups at least three completed tools from the same semantic family', () => {
    const blocks = [
      block('read-1', 'tool', 'read'),
      block('search-1', 'tool', 'grep'),
      block('list-1', 'tool', 'glob'),
    ]

    const result = groupConsecutiveToolCalls(blocks)

    expect(result).toHaveLength(1)
    expect((result[0] as ToolBlockGroup).kind).toBe('group')
    expect((result[0] as ToolBlockGroup).id).toBe('tool-group-read-1')
    expect((result[0] as ToolBlockGroup).toolName).toBe('read')
    expect((result[0] as ToolBlockGroup).blocks).toEqual(blocks)
  })

  it('keeps thinking as a visible boundary', () => {
    const thinking = block('thinking-1', 'thinking')
    const blocks = [
      block('read-1', 'tool', 'read'),
      block('search-1', 'tool', 'grep'),
      block('list-1', 'tool', 'glob'),
      thinking,
      block('read-2', 'tool', 'read'),
      block('search-2', 'tool', 'grep'),
      block('list-2', 'tool', 'glob'),
    ]

    const result = groupConsecutiveToolCalls(blocks)

    expect(result).toHaveLength(3)
    expect((result[0] as ToolBlockGroup).kind).toBe('group')
    expect(result[1]).toBe(thinking)
    expect((result[2] as ToolBlockGroup).kind).toBe('group')
  })

  it('does not collapse only two completed tools', () => {
    const result = groupConsecutiveToolCalls([
      block('read-1', 'tool', 'read'),
      block('search-1', 'tool', 'grep'),
    ])

    expect(result).toHaveLength(2)
    expect(result.every((item) => !('kind' in item))).toBe(true)
  })

  it('does not merge tools from different semantic families', () => {
    const result = groupConsecutiveToolCalls([
      block('read-1', 'tool', 'read'),
      block('browser-1', 'tool', 'webbridge'),
      block('edit-1', 'tool', 'edit'),
    ])

    expect(result).toHaveLength(3)
    expect(result.every((item) => !('kind' in item))).toBe(true)
  })

  it('keeps unfinished tools visible while streaming', () => {
    const pending = block('read-2', 'tool', 'read')
    pending.toolDone = false
    const result = groupConsecutiveToolCalls([
      block('read-1', 'tool', 'read'),
      pending,
      block('read-3', 'tool', 'read'),
    ])

    expect(result).toHaveLength(3)
    expect(result[1]).toBe(pending)
    expect(result.every((item) => !('kind' in item))).toBe(true)
  })
})
