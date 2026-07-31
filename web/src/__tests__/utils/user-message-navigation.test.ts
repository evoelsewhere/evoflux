import { describe, expect, it } from 'vitest'

import type { ContentBlock } from '@/api/types'
import { partitionTurns } from '@/utils/turns'
import { buildUserMessageNavigationItems } from '@/utils/user-message-navigation'

function navigationItems(blocks: ContentBlock[]) {
  return buildUserMessageNavigationItems(partitionTurns(blocks))
}

describe('buildUserMessageNavigationItems', () => {
  it('pairs direct prompts with the final prose response and tool labels', () => {
    const items = navigationItems([
      { id: 'user-1', type: 'user', content: 'Build the feature' },
      { id: 'thinking-1', type: 'thinking', content: 'Internal work' },
      { id: 'text-1', type: 'text', content: 'Initial answer' },
      { id: 'tool-1', type: 'tool', content: '', toolName: 'shell' },
      { id: 'tool-2', type: 'tool', content: '', toolName: 'shell' },
      { id: 'text-2', type: 'text', content: 'Final answer' },
      { id: 'user-2', type: 'user', content: 'Verify it' },
      { id: 'text-3', type: 'text', content: 'All checks pass' },
    ])

    expect(items).toEqual([
      {
        id: 'user-1',
        label: 'Build the feature',
        response: 'Final answer',
        toolNames: ['shell'],
        turnIndex: 0,
      },
      {
        id: 'user-2',
        label: 'Verify it',
        response: 'All checks pass',
        toolNames: [],
        turnIndex: 2,
      },
    ])
  })

  it('filters agent inbox and empty messages while retaining attachment prompts', () => {
    const items = navigationItems([
      { id: 'empty', type: 'user', content: '   ' },
      { id: 'empty-response', type: 'text', content: 'Not navigable' },
      {
        id: 'inbox',
        type: 'user',
        content: 'Delegated update',
        extra: { from_agent: 'reviewer' },
      },
      { id: 'inbox-response', type: 'text', content: 'Not a user turn' },
      {
        id: 'attachment',
        type: 'user',
        content: '',
        attachments: [{ original_name: 'design.png', category: 'image' }],
      },
      { id: 'attachment-response', type: 'text', content: 'I can see it' },
    ])

    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({
      id: 'attachment',
      label: 'design.png',
      response: 'I can see it',
    })
  })

  it('removes Markdown syntax from response previews', () => {
    const items = navigationItems([
      { id: 'user-1', type: 'user', content: 'Dự báo cả tuần' },
      {
        id: 'text-1',
        type: 'text',
        content: '## Dự báo thời tiết\n\nTuần này **nóng** với [chi tiết](https://example.com) và `34°C`.',
      },
    ])

    expect(items[0]?.response).toBe('Dự báo thời tiết')
  })
})
