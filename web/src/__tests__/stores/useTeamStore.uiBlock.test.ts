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
import { useUIStore } from '@/stores/useUIStore'
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

describe('sse-reducer visual_artifact case', () => {
  it('opens new rich output in the Workbench and updates the same tab on revisions', () => {
    useUIStore.setState((state) => {
      state.workbenchTabs = []
      state.workbenchSessionId = 'session-1'
      state.activeWorkbenchTabId = null
      state.activeWorkbenchTool = null
      state.workbenchOpen = false
    })
    useTeamStore.setState({ sessionId: 'session-1' })
    const payload = {
      type: 'visual_artifact', agent: 'lead', tool_call_id: 'artifact-call-1', artifact_id: 'trip-dashboard',
      kind: 'dashboard', title: 'Trip dashboard', summary: 'Spend by day',
      source_html: '<main>chart</main>', sources: [], duration_ms: null,
    }

    handle('visual_artifact', payload)
    expect(useUIStore.getState().activeWorkbenchTool).toBe('visual-artifact')
    expect(useUIStore.getState().workbenchTabs[0]?.artifact?.revision).toBe(1)

    handle('visual_artifact', { ...payload, tool_call_id: 'artifact-call-2', title: 'Updated trip dashboard' })
    expect(useUIStore.getState().workbenchTabs).toHaveLength(1)
    expect(useUIStore.getState().workbenchTabs[0]?.artifact).toMatchObject({
      artifactId: 'trip-dashboard', revision: 2, title: 'Updated trip dashboard',
    })
  })

  it('does not take over the Workbench for an event from a non-active session', () => {
    useUIStore.setState((state) => {
      state.workbenchTabs = []
      state.workbenchSessionId = 'session-visible'
      state.activeWorkbenchTabId = null
      state.activeWorkbenchTool = null
      state.workbenchOpen = false
    })
    useTeamStore.setState({ sessionId: 'session-background' })
    handle('visual_artifact', {
      type: 'visual_artifact', agent: 'lead', tool_call_id: 'call-bg', artifact_id: 'background',
      kind: 'dashboard', title: 'Background', summary: 'Background work', source_html: '<main />',
      sources: [], duration_ms: null,
    })
    expect(useUIStore.getState().activeWorkbenchTool).toBeNull()
    expect(useUIStore.getState().workbenchTabs).toEqual([])
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

function flushedLeadBlocks(): ContentBlock[] {
  return useTeamStore.getState().agentStreams.lead?.blocks ?? []
}

const NEXT_NODES = [
  { type: 'callout', tone: 'info', body: 'next' },
  { type: 'stat_cards', cards: [{ label: 'RAM', value: 7 }] },
]

describe('sse-reducer ui_block identity protocol (spec §1.4/§1.6)', () => {
  it('replace hits currentBlocks in place — index/id preserved, identity immutable', () => {
    handle('ui_block', {
      agent: 'lead',
      tool_call_id: 'call-1',
      block_id: 'a',
      blocks: NODES,
    })
    handle('ui_block', {
      agent: 'lead',
      tool_call_id: 'call-2',
      block_id: 'b',
      blocks: NODES,
      metadata: { title: 'B' },
    })
    handle('ui_block', {
      agent: 'lead',
      tool_call_id: 'call-3',
      block_id: 'c',
      blocks: NODES,
    })
    const before = uiBlocks()
    expect(before.map((b) => b.uiBlockIdentity)).toEqual(['a', 'b', 'c'])
    const middleId = before[1].id

    handle('ui_block', {
      agent: 'lead',
      tool_call_id: 'call-4',
      replace_id: 'b',
      blocks: NEXT_NODES,
    })

    const blocks = uiBlocks()
    expect(blocks).toHaveLength(3)
    expect(blocks[1].id).toBe(middleId)
    expect(blocks[1].uiBlockIdentity).toBe('b')
    expect(blocks[1].uiBlocks).toEqual(NEXT_NODES)
    // Later call supplied no title — the original title survives.
    expect(blocks[1].title).toBe('B')
    // Latest writer refreshes toolCallId (§1.6).
    expect(blocks[1].toolCallId).toBe('call-4')
  })

  it('same-block_id upserts without appending or moving the group', () => {
    handle('ui_block', {
      agent: 'lead',
      tool_call_id: 'call-1',
      block_id: 'metrics',
      blocks: NODES,
      metadata: { title: 'Metrics' },
    })
    const before = uiBlocks()
    const id = before[0].id

    handle('ui_block', {
      agent: 'lead',
      tool_call_id: 'call-2',
      block_id: 'metrics',
      blocks: NEXT_NODES,
    })

    const blocks = uiBlocks()
    expect(blocks).toHaveLength(1)
    expect(blocks[0].id).toBe(id)
    expect(blocks[0].uiBlockIdentity).toBe('metrics')
    expect(blocks[0].uiBlocks).toEqual(NEXT_NODES)
    expect(blocks[0].title).toBe('Metrics')
    expect(blocks[0].toolCallId).toBe('call-2')
  })

  it('unmatched replace_id appends with identity = replace_id', () => {
    handle('ui_block', {
      agent: 'lead',
      tool_call_id: 'call-1',
      replace_id: 'ghost',
      blocks: NODES,
    })
    const blocks = uiBlocks()
    expect(blocks).toHaveLength(1)
    expect(blocks[0].uiBlockIdentity).toBe('ghost')
  })

  it('replace hits a group flushed into stream.blocks', () => {
    handle('ui_block', {
      agent: 'lead',
      tool_call_id: 'call-1',
      block_id: 'metrics',
      blocks: NODES,
      metadata: { title: 'Metrics' },
    })
    const id = uiBlocks()[0].id

    handle('done', {}) // flush: currentBlocks → stream.blocks
    expect(uiBlocks()).toHaveLength(0)
    expect(flushedLeadBlocks().filter((b) => b.type === 'ui_block')).toHaveLength(1)

    handle('ui_block', {
      agent: 'lead',
      tool_call_id: 'call-2',
      replace_id: 'metrics',
      blocks: NEXT_NODES,
    })

    // The hit lives in the flushed history — no duplicate, no re-append.
    expect(uiBlocks()).toHaveLength(0)
    const flushed = flushedLeadBlocks().filter((b) => b.type === 'ui_block')
    expect(flushed).toHaveLength(1)
    expect(flushed[0].id).toBe(id)
    expect(flushed[0].uiBlockIdentity).toBe('metrics')
    expect(flushed[0].uiBlocks).toEqual(NEXT_NODES)
  })

  it('double-replay converges to a single group with final content', () => {
    const create = {
      agent: 'lead',
      tool_call_id: 'call-1',
      block_id: 'metrics',
      blocks: NODES,
      metadata: { title: 'A' },
    }
    const replace = {
      agent: 'lead',
      tool_call_id: 'call-2',
      replace_id: 'metrics',
      blocks: NEXT_NODES,
      metadata: { title: 'B' },
    }
    handle('ui_block', create)
    handle('ui_block', replace)
    const firstId = uiBlocks()[0].id

    // Replay both events again (reconnect / reload).
    handle('ui_block', create)
    handle('ui_block', replace)

    const blocks = uiBlocks()
    expect(blocks).toHaveLength(1)
    expect(blocks[0].id).toBe(firstId)
    expect(blocks[0].uiBlocks).toEqual(NEXT_NODES)
    expect(blocks[0].title).toBe('B')
  })

  it('does not match identity across agents', () => {
    handle('ui_block', {
      agent: 'lead',
      tool_call_id: 'call-1',
      block_id: 'metrics',
      blocks: NODES,
    })
    handle('ui_block', {
      agent: 'research',
      tool_call_id: 'call-2',
      block_id: 'metrics',
      blocks: NEXT_NODES,
    })

    expect(uiBlocks()).toHaveLength(1)
    expect(uiBlocks()[0].uiBlocks).toEqual(NODES)
    const research = (useTeamStore.getState().agentStreams.research?.currentBlocks ?? [])
      .filter((b) => b.type === 'ui_block')
    expect(research).toHaveLength(1)
    expect(research[0].uiBlocks).toEqual(NEXT_NODES)
  })

  it('tool_end fallback honors replace_id from args (upsert, no duplicate)', () => {
    handle('ui_block', {
      agent: 'lead',
      tool_call_id: 'call-1',
      block_id: 'metrics',
      blocks: NODES,
      metadata: { title: 'Metrics' },
    })
    // The second call's ui_block event never arrived — only tool_start/end.
    handle('tool_start', {
      agent: 'lead',
      name: 'ui_block',
      tool_call_id: 'call-2',
      arguments: JSON.stringify({ blocks: NEXT_NODES, replace_id: 'metrics' }),
    })
    handle('tool_end', {
      agent: 'lead',
      name: 'ui_block',
      tool_call_id: 'call-2',
      result: 'Rendered 2 UI block(s)',
    })

    const blocks = uiBlocks()
    expect(blocks).toHaveLength(1)
    expect(blocks[0].uiBlockIdentity).toBe('metrics')
    expect(blocks[0].uiBlocks).toEqual(NEXT_NODES)
    // Fallback args carried no title — the group's title survives.
    expect(blocks[0].title).toBe('Metrics')
  })

  it('tool_end fallback honors block_id from args (upsert by identity)', () => {
    handle('ui_block', {
      agent: 'lead',
      tool_call_id: 'call-1',
      block_id: 'metrics',
      blocks: NODES,
    })
    handle('tool_start', {
      agent: 'lead',
      name: 'ui_block',
      tool_call_id: 'call-2',
      arguments: JSON.stringify({ blocks: NEXT_NODES, block_id: 'metrics' }),
    })
    handle('tool_end', {
      agent: 'lead',
      name: 'ui_block',
      tool_call_id: 'call-2',
      result: 'Rendered 2 UI block(s)',
    })

    const blocks = uiBlocks()
    expect(blocks).toHaveLength(1)
    expect(blocks[0].uiBlockIdentity).toBe('metrics')
    expect(blocks[0].uiBlocks).toEqual(NEXT_NODES)
    expect(blocks[0].toolCallId).toBe('call-2')
  })
})
