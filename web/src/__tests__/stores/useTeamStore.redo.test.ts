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

import { createDefaultAgentStream } from '@/stores/useTeamStore/defaults'
import { useTeamStore } from '@/stores/useTeamStore'

beforeEach(() => {
  vi.clearAllMocks()
  useTeamStore.setState({
    sessionId: 'session-1',
    leadName: 'lead',
    agentNames: ['lead'],
    agentStreams: { lead: createDefaultAgentStream() },
    isTeamWorking: false,
    turnChanges: null,
    _leadRevertTime: Date.now(),
    error: null,
  })
})

describe('redo back to the live tip', () => {
  it('brings back the latest turn’s "Edited N files" summary', async () => {
    apiMocks.postTeamCommand.mockResolvedValue({
      message: null,
      changed_paths: { added: [], modified: ['README.md'], removed: [] },
    })
    apiMocks.teamHistory.mockResolvedValue({
      lead: {
        running: false,
        messages: [
          {
            id: 'u1',
            role: 'user',
            content: 'edit the readme',
            extra: {
              turn_changes: {
                additions: 1,
                deletions: 0,
                files: [{ path: 'README.md', status: 'modified', additions: 1, deletions: 0 }],
              },
            },
          },
          { id: 'a1', role: 'assistant', content: 'done' },
        ],
      },
    })

    await useTeamStore.getState().redoTeam()

    const summary = useTeamStore.getState().turnChanges
    expect(summary?.files.map((file) => file.path)).toEqual(['README.md'])
    expect(useTeamStore.getState().error).toBeNull()
  })
})
