import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMocks = vi.hoisted(() => ({
  cancelQueuedTeamMessage: vi.fn(), getRegistry: vi.fn(), listTeamAgents: vi.fn(),
  postTeamChat: vi.fn(), postTeamCommand: vi.fn(), teamHistory: vi.fn(), teamStream: vi.fn(),
}))
vi.mock('@/api/client', () => apiMocks)

import { queryClient } from '@/lib/query-client'
import { useTeamStore } from '@/stores/useTeamStore'
import type { ContentBlock } from '@/api/types'

beforeEach(() => {
  queryClient.clear()
  vi.clearAllMocks()
  apiMocks.getRegistry.mockResolvedValue({ models: [] })
  apiMocks.listTeamAgents.mockResolvedValue({ agents: [{ name: 'lead', is_lead: true, model: null }], blueprints: [] })
  useTeamStore.getState().beginResolvedSession(null)
})

function handle(type: string, data: Record<string, unknown>) {
  useTeamStore.getState()._handleSSEEvent(type, data)
}

function motionBlocks(): ContentBlock[] {
  return useTeamStore.getState().agentStreams.lead?.currentBlocks.filter((block) => block.type === 'motion_progress' || block.type === 'visual_artifact') ?? []
}

const progress = (sequence: number, revision = 1, phase = 'storyboard') => ({
  type: 'motion_progress', agent: 'lead', job_id: `motion-${'a'.repeat(32)}`, sequence,
  artifact_id: 'rainfall-story', artifact_revision: revision,
  status: 'running', phase, beat: { id: 'collect', index: 0, total: 4, title: 'Collect' },
  frames: { scope: 'review_samples', completed: sequence, total: 4, fps: 24, last_completed_index: sequence - 1 },
  iteration: { current: 1, budget: 3 }, audio_status: 'pending', selected_samples: [],
})

describe('motion progress SSE reducer', () => {
  it('keeps one card per job, rejects duplicate and out-of-order sequence numbers', () => {
    handle('motion_progress', progress(1))
    handle('motion_progress', progress(3, 1, 'composing'))
    handle('motion_progress', progress(2, 1, 'storyboard'))
    handle('motion_progress', progress(3, 1, 'composing'))

    const blocks = motionBlocks()
    expect(blocks).toHaveLength(1)
    expect(blocks[0].motionProgress).toMatchObject({ sequence: 3, phase: 'composing', frames: { completed: 3 } })
  })

  it('replaces progress on a newer artifact revision and merges the final artifact into that same card', () => {
    handle('motion_progress', progress(2, 1, 'reviewing'))
    const originalId = motionBlocks()[0].id
    handle('motion_progress', progress(3, 2, 'revising'))
    expect(motionBlocks()[0].motionProgress).toMatchObject({ sequence: 3, artifactRevision: 2, phase: 'revising' })

    handle('visual_artifact', {
      type: 'visual_artifact', agent: 'lead', tool_call_id: 'stale-call', artifact_id: 'rainfall-story',
      artifact_revision: 1, kind: 'motion', title: 'Stale render', summary: 'Old revision',
      source_html: '<main>Old</main>', sources: [], duration_ms: 9000,
    })
    expect(motionBlocks()[0].type).toBe('motion_progress')

    handle('visual_artifact', {
      type: 'visual_artifact', agent: 'lead', tool_call_id: 'artifact-call', artifact_id: 'rainfall-story',
      kind: 'motion', title: 'Clean water journey', summary: 'Four beats', source_html: '<main>Animation</main>',
      sources: [], duration_ms: 9000,
      artifact_revision: 2,
    })
    const blocks = motionBlocks()
    expect(blocks).toHaveLength(1)
    expect(blocks[0].id).toBe(originalId)
    expect(blocks[0].type).toBe('visual_artifact')
    expect(blocks[0].visualArtifact).toMatchObject({ artifactId: 'rainfall-story', revision: 2 })
    expect(blocks[0].motionProgress).toMatchObject({ artifactRevision: 2 })
  })

  it('ignores stale revisions and malformed counters', () => {
    handle('motion_progress', progress(4, 2, 'composing'))
    handle('motion_progress', progress(3, 1, 'storyboard'))
    handle('motion_progress', { ...progress(6, 2), frames: { scope: 'final_output', completed: 9, total: 4 } })
    expect(motionBlocks()[0].motionProgress).toMatchObject({ sequence: 4, artifactRevision: 2 })
  })
})
