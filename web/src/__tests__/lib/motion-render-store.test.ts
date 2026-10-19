import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MotionRenderSnapshot, MotionReviewSample } from '@/lib/motion-render-store'
import { getMotionRenderSnapshot, publishMotionRenderSnapshot, subscribeMotionRender } from '@/lib/motion-render-store'

let artifactSequence = 0

function sample(sampleId: string): MotionReviewSample {
  return { sampleId, beatId: 'beat-1', frameIndex: 0, timestampMs: 0, role: 'style', objectUrl: `blob:${sampleId}` }
}

function snapshot(overrides: Partial<MotionRenderSnapshot> = {}): MotionRenderSnapshot {
  return {
    artifactId: `motion-store-test-${++artifactSequence}`, revision: 1, renderId: 'render-1',
    status: 'rendering', completedFrames: 0, totalFrames: 10, fps: 30,
    lastCompletedIndex: null, currentTimeMs: 0, currentFrameUrl: null, beats: [], samples: [], audioStatus: 'not_requested',
    ...overrides,
  }
}

describe('motion render store', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('keeps frame counts monotonic within one render', () => {
    const first = snapshot({ completedFrames: 5, lastCompletedIndex: 4 })
    expect(publishMotionRenderSnapshot(first)).toBe(true)
    expect(publishMotionRenderSnapshot({ ...first, completedFrames: 4, lastCompletedIndex: 3 })).toBe(false)
    expect(getMotionRenderSnapshot(first.artifactId, first.revision)?.completedFrames).toBe(5)
  })

  it('replaces older revisions and rejects stale updates', () => {
    const revoke = vi.spyOn(URL, 'revokeObjectURL')
    const old = snapshot({ samples: [sample('old-preview')] })
    expect(publishMotionRenderSnapshot(old)).toBe(true)
    const newer = { ...old, revision: 2, renderId: 'render-2', completedFrames: 2, samples: [] }
    expect(publishMotionRenderSnapshot(newer)).toBe(true)
    expect(publishMotionRenderSnapshot(old)).toBe(false)
    expect(getMotionRenderSnapshot(newer.artifactId, 1)).toBeNull()
    expect(getMotionRenderSnapshot(newer.artifactId, 2)?.completedFrames).toBe(2)
    expect(revoke).toHaveBeenCalledWith('blob:old-preview')
  })

  it('retains at most twelve selected previews and revokes trimmed object URLs', () => {
    const revoke = vi.spyOn(URL, 'revokeObjectURL')
    const previews = Array.from({ length: 13 }, (_, index) => sample(`preview-${index}`))
    const value = snapshot({ samples: previews })

    expect(publishMotionRenderSnapshot(value)).toBe(true)
    expect(getMotionRenderSnapshot(value.artifactId, 1)?.samples).toHaveLength(12)
    expect(revoke).toHaveBeenCalledWith('blob:preview-12')
  })

  it('clears and revokes sample previews when a render is cancelled', () => {
    const revoke = vi.spyOn(URL, 'revokeObjectURL')
    const started = snapshot({ currentFrameUrl: 'blob:current-frame', samples: [sample('cancel-preview')] })
    const updates: Array<MotionRenderSnapshot | null> = []
    const unsubscribe = subscribeMotionRender(started.artifactId, started.revision, (value) => updates.push(value))

    publishMotionRenderSnapshot(started)
    publishMotionRenderSnapshot({ ...started, status: 'cancelled', currentFrameUrl: null, samples: [] })

    expect(getMotionRenderSnapshot(started.artifactId, started.revision)?.samples).toEqual([])
    expect(revoke).toHaveBeenCalledWith('blob:cancel-preview')
    expect(revoke).toHaveBeenCalledWith('blob:current-frame')
    expect(updates.at(-1)?.status).toBe('cancelled')
    unsubscribe()
  })

  it('allows a new render run of the same revision to restart its counter', () => {
    const completed = snapshot({ status: 'complete', completedFrames: 10, lastCompletedIndex: 9 })
    expect(publishMotionRenderSnapshot(completed)).toBe(true)
    expect(publishMotionRenderSnapshot({ ...completed, renderId: 'render-2', completedFrames: 0, lastCompletedIndex: null })).toBe(true)
    expect(getMotionRenderSnapshot(completed.artifactId, completed.revision)?.completedFrames).toBe(0)
  })
})
