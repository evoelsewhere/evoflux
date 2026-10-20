import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { BlockRenderer } from '@/components/BlockRenderer'
import type { ContentBlock } from '@/api/types'

const apiMocks = vi.hoisted(() => ({
  cancelQueuedTeamMessage: vi.fn(),
  getRegistry: vi.fn(),
  listTeamAgents: vi.fn(),
  postTeamChat: vi.fn(),
  postTeamCommand: vi.fn(),
  teamHistory: vi.fn(),
  teamStream: vi.fn(),
}))
vi.mock('@/api/client', () => apiMocks)

import { queryClient } from '@/lib/query-client'
import { useTeamStore } from '@/stores/useTeamStore'
import { parseTeamBlocks } from '@/utils/messages'
import type { MessageResponse } from '@/api/types'

function noticeBlock(extra: Record<string, unknown>, content = 'raw notice text'): ContentBlock {
  return {
    id: 'notice-1',
    type: 'user',
    content,
    extra: { from_agent: 'background_task', kind: 'task_event', ...extra },
  } as ContentBlock
}

beforeEach(() => {
  queryClient.clear()
  vi.clearAllMocks()
  apiMocks.getRegistry.mockResolvedValue({ models: [] })
  apiMocks.listTeamAgents.mockResolvedValue({
    agents: [{ name: 'lead', is_lead: true, model: null }],
    blueprints: [],
  })
  useTeamStore.getState().beginResolvedSession(null)
})

describe('BackgroundTaskNotice', () => {
  it('shows a finished task as a status card, not an agent message', () => {
    render(
      <BlockRenderer
        block={noticeBlock({
          task_event: 'exited',
          status: 'succeeded',
          exit_code: 0,
          duration_ms: 4200,
          command: 'bun run build',
        })}
        isStreaming={false}
      />,
    )

    expect(screen.getByText('Background task finished')).toBeInTheDocument()
    expect(screen.getByText('bun run build')).toBeInTheDocument()
    expect(screen.getByText('4.2s')).toBeInTheDocument()
    expect(screen.queryByText(/Message from/)).not.toBeInTheDocument()
  })

  it('names the exit code of a failed task and a timeout', () => {
    const { rerender } = render(
      <BlockRenderer
        block={noticeBlock({ task_event: 'exited', status: 'failed', exit_code: 3 })}
        isStreaming={false}
      />,
    )
    expect(screen.getByText('Background task failed (exit code 3)')).toBeInTheDocument()

    rerender(
      <BlockRenderer
        block={noticeBlock({ task_event: 'exited', status: 'timed_out', exit_code: -9 })}
        isStreaming={false}
      />,
    )
    expect(screen.getByText('Background task timed out')).toBeInTheDocument()
  })

  it('shows the matched line for a notify_on match while the task keeps running', () => {
    render(
      <BlockRenderer
        block={noticeBlock({
          task_event: 'matched',
          status: 'running',
          matched_line: 'listening on 8000',
        })}
        isStreaming={false}
      />,
    )

    expect(screen.getByText('Background task output matched')).toBeInTheDocument()
    expect(screen.getByText('listening on 8000')).toBeInTheDocument()
  })

  it('keeps the full notice behind a disclosure', () => {
    render(
      <BlockRenderer
        block={noticeBlock({ task_event: 'exited', status: 'succeeded' }, '12 passed')}
        isStreaming={false}
      />,
    )

    expect(screen.queryByText('12 passed')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Output' }))
    expect(screen.getByText('12 passed')).toBeInTheDocument()
  })
})

describe('background task notices in the store and history', () => {
  const event = {
    kind: 'task_event',
    task_event: 'exited',
    process_id: 'proc_0123456789',
    command: 'pytest -q',
    status: 'succeeded',
    exit_code: 0,
    duration_ms: 1000,
  }

  it('turns a live inbox event into the same flat block a reload produces', () => {
    useTeamStore.getState()._handleSSEEvent('inbox', {
      agent: 'lead',
      content: '[Background task proc_0123456789 finished: Succeeded]',
      from_agent: 'background_task',
      task_event: { ...event, kind: undefined },
    })

    const blocks = useTeamStore.getState().agentStreams.lead.currentBlocks
    const live = blocks.find((block) => block.type === 'user')
    expect(live?.extra).toMatchObject({
      from_agent: 'background_task',
      kind: 'task_event',
      task_event: 'exited',
      process_id: 'proc_0123456789',
      exit_code: 0,
    })

    const reloaded = parseTeamBlocks([
      {
        id: 'row-1',
        role: 'user',
        content: '[Background task proc_0123456789 finished: Succeeded]',
        extra: { ...event, from_agent: 'background_task', message_id: 'm1' },
        created_at: '2026-01-01T00:00:00Z',
      } as unknown as MessageResponse,
    ]).find((block) => block.type === 'user')
    expect(reloaded?.extra).toMatchObject({
      from_agent: 'background_task',
      kind: 'task_event',
      task_event: 'exited',
      process_id: 'proc_0123456789',
    })
  })

  it('does not count a notice as a message the user sent', async () => {
    const { isDirectUserBlock } = await import('@/utils/blocks')
    expect(isDirectUserBlock(noticeBlock({ task_event: 'exited' }))).toBe(false)
  })
})
