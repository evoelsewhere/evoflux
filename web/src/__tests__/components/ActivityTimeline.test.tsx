import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ActivityTimeline } from '@/components/ActivityTimeline'
import { AssistantTurnContent } from '@/components/AssistantTurnContent'
import { segmentAssistantTurn } from '@/utils/activity-timeline'
import { useUIStore } from '@/stores/useUIStore'
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
  useUIStore.setState({ easdRunOpenRequest: null, easdSelectedRunId: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('segmentAssistantTurn', () => {
  it('uses content as a stable boundary between activity groups', () => {
    const blocks = [
      block('commentary-1', 'text', 'I will inspect the flow.'),
      block('thought-1', 'thinking', 'Planning'),
      block('tool-1', 'tool'),
      block('commentary-2', 'text', 'The first issue is confirmed.'),
      block('thought-2', 'thinking', 'Reviewing'),
      block('tool-2', 'tool'),
      block('answer', 'text', 'Final answer'),
    ]

    const segments = segmentAssistantTurn(blocks)

    expect(segments.map((segment) => ({
      kind: segment.kind,
      ids: segment.blocks.map((item) => item.id),
    }))).toEqual([
      { kind: 'content', ids: ['commentary-1'] },
      { kind: 'activity', ids: ['thought-1', 'tool-1'] },
      { kind: 'content', ids: ['commentary-2'] },
      { kind: 'activity', ids: ['thought-2', 'tool-2'] },
      { kind: 'content', ids: ['answer'] },
    ])
  })

  it('keeps durable delegation cards outside the bounded activity log', () => {
    const read = block('tool-read', 'tool')
    const delegation = {
      ...block('tool-delegate', 'tool'),
      toolName: 'team_delegate',
    }

    const segments = segmentAssistantTurn([read, delegation])
    expect(segments.map((segment) => ({
      kind: segment.kind,
      ids: segment.blocks.map((item) => item.id),
    }))).toEqual([
      { kind: 'activity', ids: ['tool-read'] },
      { kind: 'content', ids: ['tool-delegate'] },
    ])

    const { container } = render(
      <AssistantTurnContent
        blocks={[read, delegation]}
        turnIsStreaming={false}
        renderBlock={({ block: item }) => (
          <div data-testid={item.id}>{item.toolName}</div>
        )}
      />,
    )

    const boundedLog = container.querySelector('.activity-timeline-scroll')
    expect(boundedLog).toContainElement(screen.getByTestId('tool-read'))
    expect(boundedLog).not.toContainElement(screen.getByTestId('tool-delegate'))
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

    fireEvent.click(
      screen.getByRole('button', { name: 'Expand Read files, 4 activities' }),
    )

    const ordered = [
      screen.getByTestId('thought-1'),
      screen.getByTestId('tool-1'),
      screen.getByTestId('thought-2'),
      screen.getByTestId('tool-2'),
    ]
    ordered.slice(0, -1).forEach((node, index) => {
      expect(node.compareDocumentPosition(ordered[index + 1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    })
    expect(screen.getByRole('log', { name: 'Activity history' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Collapse Read files, 4 activities' })).toBeInTheDocument()
  })

  it('keeps a live group collapsed until the reader opens it', () => {
    render(
      <ActivityTimeline
        blocks={[block('tool', 'tool')]}
        isActive
        renderBlock={renderBlock}
      />,
    )

    expect(
      screen.getByRole('button', { name: 'Expand Read files, 1 activity' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('log', { name: 'Activity history' }),
    ).not.toBeInTheDocument()
  })

  it('keeps a live group collapsed as further activity streams in', () => {
    const first = block('tool-1', 'tool')
    const { rerender } = render(
      <ActivityTimeline blocks={[first]} isActive renderBlock={renderBlock} />,
    )

    rerender(
      <ActivityTimeline
        blocks={[first, block('tool-2', 'tool')]}
        isActive
        renderBlock={renderBlock}
      />,
    )

    expect(
      screen.getByRole('button', { name: 'Expand Read files, 2 activities' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('log', { name: 'Activity history' }),
    ).not.toBeInTheDocument()
  })

  it('collapses completed activity to one summary row and expands on request', () => {
    render(
      <ActivityTimeline
        blocks={[block('tool', 'tool')]}
        isActive={false}
        renderBlock={renderBlock}
      />,
    )

    const summary = screen.getByRole('button', { name: 'Expand Read files, 1 activity' })
    expect(screen.queryByRole('log', { name: 'Activity history' })).not.toBeInTheDocument()

    fireEvent.click(summary)
    expect(screen.getByRole('log', { name: 'Activity history' })).toBeInTheDocument()
  })

  it('keeps a successful EASD review action visible while activity is collapsed', () => {
    const submit = {
      ...block('submit', 'tool'),
      toolName: 'easd_submit_plan',
      toolArgs: JSON.stringify({ run_id: 'run-plan' }),
      toolResult: 'Plan draft persisted for user review. revision=plan-1 hash=abc.',
    }
    render(
      <ActivityTimeline
        blocks={[block('read', 'tool'), submit]}
        isActive={false}
        renderBlock={renderBlock}
      />,
    )

    expect(screen.queryByRole('log', { name: 'Activity history' })).not.toBeInTheDocument()
    expect(screen.getByText('Draft persisted · user review is the next EASD step.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Review plan' }))
    expect(useUIStore.getState().easdRunOpenRequest).toMatchObject({ runId: 'run-plan' })
  })

  it('opens historical activity at the beginning instead of the live tail', () => {
    const frames: FrameRequestCallback[] = []
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frames.push(callback)
      return frames.length
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())

    render(
      <ActivityTimeline
        blocks={[block('tool-1', 'tool'), block('tool-2', 'tool')]}
        isActive={false}
        renderBlock={renderBlock}
      />,
    )

    const log = screen.getByRole('log', { name: 'Activity history', hidden: true })
    Object.defineProperties(log, {
      clientHeight: { configurable: true, value: 100 },
      scrollHeight: { configurable: true, value: 500 },
      scrollTop: { configurable: true, writable: true, value: 400 },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Expand Read files, 2 activities' }))
    act(() => {
      while (frames.length > 0) frames.shift()?.(16)
    })

    expect(log.scrollTop).toBe(0)
  })

  it('preserves the open group when final answer prose begins', () => {
    const blocks = [block('tool', 'tool')]
    const { rerender } = render(
      <ActivityTimeline blocks={blocks} isActive renderBlock={renderBlock} />,
    )
    fireEvent.click(
      screen.getByRole('button', { name: 'Expand Read files, 1 activity' }),
    )
    expect(screen.getByRole('log', { name: 'Activity history' })).toBeInTheDocument()

    rerender(<ActivityTimeline blocks={blocks} isActive={false} renderBlock={renderBlock} />)

    expect(screen.getByRole('log', { name: 'Activity history' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Collapse Read files, 1 activity' })).toBeInTheDocument()
  })

  it('preserves a live reader collapse while later activity arrives', () => {
    const first = block('tool-1', 'tool')
    const { rerender } = render(
      <ActivityTimeline blocks={[first]} isActive renderBlock={renderBlock} />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Expand Read files, 1 activity' }))
    fireEvent.click(screen.getByRole('button', { name: 'Collapse Read files, 1 activity' }))
    expect(screen.queryByRole('log', { name: 'Activity history' })).not.toBeInTheDocument()

    rerender(
      <ActivityTimeline
        blocks={[first, block('tool-2', 'tool')]}
        isActive
        renderBlock={renderBlock}
      />,
    )

    expect(screen.getByRole('button', { name: 'Expand Read files, 2 activities' })).toBeInTheDocument()
    expect(screen.queryByRole('log', { name: 'Activity history' })).not.toBeInTheDocument()
  })

  it('stops following when the user scrolls upward and offers Latest activity', () => {
    render(
      <ActivityTimeline
        blocks={[block('tool', 'tool')]}
        isActive
        renderBlock={renderBlock}
      />,
    )
    fireEvent.click(
      screen.getByRole('button', { name: 'Expand Read files, 1 activity' }),
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
