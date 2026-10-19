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

function suggestionEvent(overrides: Record<string, unknown> = {}) {
  return {
    session_id: 'session-1',
    message: 'Run the test suite',
    reason: 'Natural next step',
    metadata: {},
    ...overrides,
  }
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

describe('next message suggestion SSE events', () => {
  it('stashes a mid-turn suggestion as pending instead of publishing it', () => {
    useTeamStore.getState()._handleSSEEvent('next_message_suggestion', suggestionEvent())

    expect(useTeamStore.getState().nextMessageSuggestion).toBeNull()
    expect(useTeamStore.getState()._pendingNextMessageSuggestion).toEqual({
      message: 'Run the test suite',
      reason: 'Natural next step',
    })
  })

  it('promotes the pending suggestion when the turn completes', () => {
    const handle = useTeamStore.getState()._handleSSEEvent
    handle('next_message_suggestion', suggestionEvent())

    handle('done', {})

    expect(useTeamStore.getState().nextMessageSuggestion).toEqual({
      message: 'Run the test suite',
      reason: 'Natural next step',
    })
    expect(useTeamStore.getState()._pendingNextMessageSuggestion).toBeNull()
  })

  it('keeps only the last suggestion within one turn', () => {
    const handle = useTeamStore.getState()._handleSSEEvent
    handle('next_message_suggestion', suggestionEvent())
    handle('next_message_suggestion', suggestionEvent({ message: 'Check the diff', reason: '' }))

    handle('done', {})

    expect(useTeamStore.getState().nextMessageSuggestion).toEqual({
      message: 'Check the diff',
      reason: '',
    })
  })

  it('clears a stale suggestion when done arrives without one', () => {
    const handle = useTeamStore.getState()._handleSSEEvent
    handle('next_message_suggestion', suggestionEvent())
    handle('done', {})
    expect(useTeamStore.getState().nextMessageSuggestion).not.toBeNull()

    handle('done', {})

    expect(useTeamStore.getState().nextMessageSuggestion).toBeNull()
    expect(useTeamStore.getState()._pendingNextMessageSuggestion).toBeNull()
  })

  it('clears both slots when the user sends a message', () => {
    const handle = useTeamStore.getState()._handleSSEEvent
    handle('next_message_suggestion', suggestionEvent())
    handle('done', {})

    useTeamStore.getState().sendMessage('my own idea').catch(() => {})

    expect(useTeamStore.getState().nextMessageSuggestion).toBeNull()
    expect(useTeamStore.getState()._pendingNextMessageSuggestion).toBeNull()
  })

  it('clears both slots when the session changes', () => {
    const handle = useTeamStore.getState()._handleSSEEvent
    handle('next_message_suggestion', suggestionEvent())
    handle('done', {})

    useTeamStore.getState().beginResolvedSession('session-9', { mode: 'coding' })

    expect(useTeamStore.getState().nextMessageSuggestion).toBeNull()
    expect(useTeamStore.getState()._pendingNextMessageSuggestion).toBeNull()
  })
})
