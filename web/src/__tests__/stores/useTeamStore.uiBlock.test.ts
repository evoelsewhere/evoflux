import { beforeEach, describe, expect, it, vi } from 'vitest'

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
import type { ContentBlock } from '@/api/types'

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

function handle(type: string, data: Record<string, unknown>) {
  useTeamStore.getState()._handleSSEEvent(type, data)
}

function leadBlocks(): ContentBlock[] {
  return useTeamStore.getState().agentStreams.lead?.currentBlocks ?? []
}

function uiBlocks(): ContentBlock[] {
  return leadBlocks().filter((b) => b.type === 'ui_block')
}

const NODES = [
  { type: 'progress', label: 'Upload', value: 1, max: 4 },
  { type: 'callout', tone: 'success', body: 'done' },
]

describe('sse-reducer ui_block case (spec §5.4)', () => {
  it('upserts a ui_block block carrying the event nodes and title', () => {
    handle('ui_block', {
      agent: 'lead',
      tool_call_id: 'call-1',
      blocks: NODES,
      is_final: true,
      metadata: { title: 'metrics' },
    })
    const blocks = uiBlocks()
    expect(blocks).toHaveLength(1)
    expect(blocks[0].toolCallId).toBe('call-1')
    expect(blocks[0].title).toBe('metrics')
    expect(blocks[0].uiBlocks).toEqual(NODES)
    expect(blocks[0].isStreaming).toBe(false)
  })

  it('dedupes duplicate events by tool_call_id (first wins, later refresh)', () => {
    const payload = {
      agent: 'lead',
      tool_call_id: 'call-1',
      blocks: NODES,
      is_final: true,
      metadata: { title: 'metrics' },
    }
    handle('ui_block', payload)
    handle('ui_block', payload)
    const blocks = uiBlocks()
    expect(blocks).toHaveLength(1)
    expect(blocks[0].uiBlocks).toEqual(NODES)
  })

  it('keeps separate tool calls as separate blocks', () => {
    handle('ui_block', {
      agent: 'lead',
      tool_call_id: 'call-1',
      blocks: NODES,
      metadata: {},
    })
    handle('ui_block', {
      agent: 'lead',
      tool_call_id: 'call-2',
      blocks: NODES,
      metadata: {},
    })
    expect(uiBlocks()).toHaveLength(2)
  })

  it('ignores events without a blocks array', () => {
    handle('ui_block', { agent: 'lead', tool_call_id: 'call-1', blocks: 'nope' })
    expect(uiBlocks()).toHaveLength(0)
  })
})

describe('sse-reducer tool_end fallback reconstruction (Feature C, §6.2)', () => {
  it('reconstructs ui_block from persisted tool args when the event missed', () => {
    const args = JSON.stringify({ blocks: NODES, title: 'from_args' })
    handle('tool_start', {
      agent: 'lead',
      name: 'ui_block',
      tool_call_id: 'call-9',
      arguments: args,
    })
    handle('tool_end', {
      agent: 'lead',
      name: 'ui_block',
      tool_call_id: 'call-9',
      result: 'Rendered 2 UI block(s)',
    })
    const blocks = uiBlocks()
    expect(blocks).toHaveLength(1)
    expect(blocks[0].toolCallId).toBe('call-9')
    expect(blocks[0].title).toBe('from_args')
    expect(blocks[0].uiBlocks).toHaveLength(2)
  })

  it('does not duplicate when the ui_block event already arrived', () => {
    handle('tool_start', {
      agent: 'lead',
      name: 'ui_block',
      tool_call_id: 'call-9',
      arguments: JSON.stringify({ blocks: NODES, title: 'from_args' }),
    })
    handle('ui_block', {
      agent: 'lead',
      tool_call_id: 'call-9',
      blocks: NODES,
      metadata: { title: 'from_event' },
    })
    handle('tool_end', {
      agent: 'lead',
      name: 'ui_block',
      tool_call_id: 'call-9',
      result: 'Rendered 2 UI block(s)',
    })
    const blocks = uiBlocks()
    expect(blocks).toHaveLength(1)
    expect(blocks[0].title).toBe('from_event')
  })

  it('replay after tool_end fallback is a no-op (still one block)', () => {
    handle('tool_start', {
      agent: 'lead',
      name: 'ui_block',
      tool_call_id: 'call-9',
      arguments: JSON.stringify({ blocks: NODES }),
    })
    handle('tool_end', {
      agent: 'lead',
      name: 'ui_block',
      tool_call_id: 'call-9',
      result: 'Rendered 2 UI block(s)',
    })
    handle('ui_block', {
      agent: 'lead',
      tool_call_id: 'call-9',
      blocks: NODES,
      metadata: {},
    })
    expect(uiBlocks()).toHaveLength(1)
  })

  it('skips reconstruction when the args carry no blocks array', () => {
    handle('tool_start', {
      agent: 'lead',
      name: 'ui_block',
      tool_call_id: 'call-9',
      arguments: JSON.stringify({ nope: true }),
    })
    handle('tool_end', {
      agent: 'lead',
      name: 'ui_block',
      tool_call_id: 'call-9',
      result: 'failed',
    })
    expect(uiBlocks()).toHaveLength(0)
    // The generic tool chip is still there for the failed call.
    expect(
      leadBlocks().some((b) => b.type === 'tool' && b.toolName === 'ui_block'),
    ).toBe(true)
  })
})
