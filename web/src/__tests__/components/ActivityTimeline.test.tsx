import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ActivityTimeline } from '@/components/ActivityTimeline'
import { partitionAssistantActivity } from '@/utils/activity-timeline'
import type { ContentBlock } from '@/api/types'

function block(id: string, type: ContentBlock['type'], content = ''): ContentBlock {
  return {
    id,
    type,
    content,
    ...(type === 'tool' ? { toolName: 'read', toolDone: true } : {}),
  }
}

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
})

describe('partitionAssistantActivity', () => {
  it('preserves the exact Thought/tool chronology and leaves final prose outside', () => {
    const blocks = [
      block('thought-1', 'thinking', 'Planning'),
      block('tool-1', 'tool'),
      block('progress', 'text', 'Checking the result'),
      block('thought-2', 'thinking', 'Reviewing'),
      block('tool-2', 'tool'),
      block('answer', 'text', 'Final answer'),
    ]

    const partition = partitionAssistantActivity(blocks)

    expect(partition.activityBlocks.map((item) => item.id)).toEqual([
      'thought-1', 'tool-1', 'progress', 'thought-2', 'tool-2',
    ])
    expect(partition.answerBlocks.map((item) => item.id)).toEqual(['answer'])
  })
})

describe('ActivityTimeline', () => {
  const renderBlock = ({ block: item, isStreaming }: { block: ContentBlock; isStreaming: boolean }) => (
    <div data-testid={item.id} data-streaming={String(isStreaming)}>{item.content}</div>
  )

  it('renders interleaved Thought and tool groups in chronological order', () => {
    render(
      <ActivityTimeline
        blocks={[
          block('thought-1', 'thinking', 'Planning'),
          block('tool-1', 'tool'),
          block('thought-2', 'thinking', 'Reviewing'),
          block('tool-2', 'tool'),
        ]}
        isActive
        renderBlock={renderBlock}
      />,
    )

    const groups = screen.getAllByRole('button', { name: /Read files, 1 action/ })
    const ordered = [
      screen.getByTestId('thought-1'),
      groups[0],
      screen.getByTestId('thought-2'),
      groups[1],
    ]
    ordered.slice(0, -1).forEach((node, index) => {
      expect(node.compareDocumentPosition(ordered[index + 1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    })
    expect(screen.getByRole('log', { name: 'Activity history' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Collapse Working · 2 actions' })).toBeInTheDocument()
  })

  it('collapses completed activity to one summary row and expands on request', () => {
    render(
      <ActivityTimeline
        blocks={[block('tool', 'tool')]}
        isActive={false}
        renderBlock={renderBlock}
      />,
    )

    const summary = screen.getByRole('button', { name: 'Expand Worked · 1 action' })
    expect(screen.queryByRole('log', { name: 'Activity history' })).not.toBeInTheDocument()

    fireEvent.click(summary)
    expect(screen.getByRole('log', { name: 'Activity history' })).toBeInTheDocument()
  })

  it('collapses the live tool history when final answer prose begins', () => {
    const blocks = [block('tool', 'tool')]
    const { rerender } = render(
      <ActivityTimeline blocks={blocks} isActive renderBlock={renderBlock} />,
    )
    expect(screen.getByRole('log', { name: 'Activity history' })).toBeInTheDocument()

    rerender(<ActivityTimeline blocks={blocks} isActive={false} renderBlock={renderBlock} />)

    expect(screen.queryByRole('log', { name: 'Activity history' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Expand Worked · 1 action' })).toBeInTheDocument()
  })

  it('stops following when the user scrolls upward and offers Latest activity', () => {
    render(
      <ActivityTimeline
        blocks={[block('tool', 'tool')]}
        isActive
        renderBlock={renderBlock}
      />,
    )

    const log = screen.getByRole('log', { name: 'Activity history' })
    Object.defineProperties(log, {
      clientHeight: { configurable: true, value: 100 },
      scrollHeight: { configurable: true, value: 500 },
      scrollTop: { configurable: true, writable: true, value: 400 },
    })
    fireEvent.wheel(log, { deltaY: -20 })

    expect(screen.getByRole('button', { name: 'Latest activity' })).toBeInTheDocument()
  })
})
