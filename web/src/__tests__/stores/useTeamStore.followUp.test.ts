import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMocks = vi.hoisted(() => ({
  cancelQueuedTeamMessage: vi.fn(),
  getRegistry: vi.fn(),
  getTeamGoal: vi.fn(),
  listTeamAgents: vi.fn(),
  postTeamChat: vi.fn(),
  postTeamCommand: vi.fn(),
  patchQueuedTeamMessage: vi.fn(),
  teamHistory: vi.fn(),
  teamStream: vi.fn(),
}))

vi.mock('@/api/client', () => apiMocks)

import { queryClient } from '@/lib/query-client'
import { createDefaultAgentStream } from '@/stores/useTeamStore/defaults'
import { useTeamStore } from '@/stores/useTeamStore'

const MODEL = 'openai:gpt-5.5'

/** Put the store in the state a running lead leaves behind. */
function withWorkingLead(sessionId = 'session-1') {
  useTeamStore.setState({
    sessionId,
    leadName: 'lead',
    agentNames: ['lead'],
    agentStreams: { lead: { ...createDefaultAgentStream(), status: 'working' } },
    sessionModel: MODEL,
    _pendingMessages: [],
    error: null,
    setupRequired: null,
  })
}

beforeEach(() => {
  queryClient.clear()
  vi.clearAllMocks()
  apiMocks.getRegistry.mockResolvedValue({ models: [{ id: MODEL }] })
  apiMocks.listTeamAgents.mockResolvedValue({
    agents: [{ name: 'lead', is_lead: true, model: null }],
    blueprints: [],
  })
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:queued-preview')
  globalThis.URL.revokeObjectURL = vi.fn()
})

describe('follow-up messages while the lead is working', () => {
  it('queues a message with its attachments instead of refusing it', async () => {
    withWorkingLead()
    apiMocks.postTeamChat.mockResolvedValue({
      status: 'queued',
      session_id: 'session-1',
      message_id: 'queued-1',
    })
    const file = new File([new Uint8Array([1, 2])], 'shot.png', { type: 'image/png' })

    const accepted = await useTeamStore.getState().sendMessage('look at this', [file])

    expect(accepted).toBe(true)
    expect(apiMocks.postTeamChat).toHaveBeenCalledTimes(1)
    expect(apiMocks.postTeamChat.mock.calls[0][3]).toEqual([file])
    expect(useTeamStore.getState().error).toBeNull()

    const [pending] = useTeamStore.getState()._pendingMessages
    expect(pending.id).toBe('queued-1')
    expect(pending.delivery).toBe('queue')
    expect(pending.attachments).toEqual([
      expect.objectContaining({ original_name: 'shot.png', category: 'image' }),
    ])
  })

  it('puts a steered message in the transcript rather than the tray', async () => {
    withWorkingLead()
    apiMocks.postTeamChat.mockResolvedValue({
      status: 'queued',
      session_id: 'session-1',
      message_id: 'steered-1',
    })

    await useTeamStore.getState().sendMessage('do this now', undefined, {
      delivery: 'steer',
    })

    // It has been sent — leaving it in the tray until the agent finishes its
    // current answer would read as if it had not gone through.
    expect(useTeamStore.getState()._pendingMessages).toEqual([])
    const blocks = useTeamStore.getState().agentStreams.lead.currentBlocks
    expect(blocks.at(-1)).toMatchObject({
      id: 'steered-1',
      type: 'user',
      content: 'do this now',
    })
  })

  it('passes the queue lane through to the request', async () => {
    withWorkingLead()
    apiMocks.postTeamChat.mockResolvedValue({
      status: 'queued',
      session_id: 'session-1',
      message_id: 'queued-2',
    })

    await useTeamStore.getState().sendMessage('after this one', undefined, {
      delivery: 'queue',
    })

    // Last positional argument of postTeamChat is the delivery lane.
    const call = apiMocks.postTeamChat.mock.calls[0]
    expect(call[call.length - 1]).toBe('queue')
    expect(useTeamStore.getState()._pendingMessages[0].delivery).toBe('queue')
  })

  it('reports a rejected queue so the composer can restore the draft', async () => {
    withWorkingLead()
    apiMocks.postTeamChat.mockRejectedValue(new Error('nope'))

    const accepted = await useTeamStore.getState().sendMessage('will fail')

    expect(accepted).toBe(false)
    expect(useTeamStore.getState().error).toBe('nope')
    expect(useTeamStore.getState()._pendingMessages).toEqual([])
  })

  it('drops the chip when a promoted message was already delivered', async () => {
    withWorkingLead()
    useTeamStore.setState({
      _pendingMessages: [
        { id: 'queued-3', sessionId: 'session-1', content: 'later', delivery: 'queue' },
      ],
    })
    apiMocks.patchQueuedTeamMessage.mockResolvedValue(false)

    useTeamStore.getState().setPendingMessageDelivery('queued-3', 'steer')
    await vi.waitFor(() => {
      expect(useTeamStore.getState()._pendingMessages).toEqual([])
    })
    expect(apiMocks.patchQueuedTeamMessage).toHaveBeenCalledWith(
      'session-1',
      'queued-3',
      { delivery: 'steer' },
    )
    expect(useTeamStore.getState().error).toBeNull()
  })
})
