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
  toolDone = true,
): ContentBlock {
  return {
    id,
    type,
    content: type === 'thinking' ? `reasoning ${id}` : '',
    toolName,
    toolDone: type === 'tool' ? toolDone : undefined,
  }
}

describe('groupConsecutiveToolCalls', () => {
  it('groups a completed activity phase', () => {
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

  it('collapses two completed tools to keep the transcript quiet', () => {
    const result = groupConsecutiveToolCalls([
      block('read-1', 'tool', 'read'),
      block('search-1', 'tool', 'grep'),
    ])

    expect(result).toHaveLength(1)
    expect((result[0] as ToolBlockGroup).kind).toBe('group')
  })

  it('summarizes mixed tool families from the same activity phase', () => {
    const result = groupConsecutiveToolCalls([
      block('read-1', 'tool', 'read'),
      block('browser-1', 'tool', 'webbridge'),
      block('edit-1', 'tool', 'edit'),
    ])

    expect(result).toHaveLength(1)
    expect((result[0] as ToolBlockGroup).blocks).toHaveLength(3)
  })

  it('creates the final group container as soon as the first tool starts', () => {
    const pending = block('read-1', 'tool', 'read', false)
    const pendingResult = groupConsecutiveToolCalls([pending])
    const completed = { ...pending, toolDone: true }
    const completedResult = groupConsecutiveToolCalls([completed])

    expect(pendingResult).toHaveLength(1)
    expect((pendingResult[0] as ToolBlockGroup).kind).toBe('group')
    expect((pendingResult[0] as ToolBlockGroup).id).toBe('tool-group-read-1')
    expect((pendingResult[0] as ToolBlockGroup).blocks).toEqual([pending])
    expect((completedResult[0] as ToolBlockGroup).id).toBe('tool-group-read-1')
  })

  it('keeps consecutive pending and completed tools in one activity run', () => {
    const pending = block('read-2', 'tool', 'read', false)
    const result = groupConsecutiveToolCalls([
      block('read-1', 'tool', 'read'),
      pending,
      block('read-3', 'tool', 'read'),
    ])

    expect(result).toHaveLength(1)
    expect((result[0] as ToolBlockGroup).blocks).toHaveLength(3)
    expect((result[0] as ToolBlockGroup).blocks[1]).toBe(pending)
  })
})
