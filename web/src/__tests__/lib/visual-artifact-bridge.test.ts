import { describe, expect, it } from 'vitest'

import { parseVisualArtifactBridgeMessage, parseVisualArtifactMessage } from '@/lib/visual-artifact-bridge'

const validArtifact = {
  type: 'visual_artifact', agent: 'assistant', tool_call_id: 'call-2',
  artifact_id: 'budget', kind: 'dashboard', title: 'Budget', summary: 'Trip spend',
  source_html: '<main>Budget</main>', scene: null, sources: [], duration_ms: null, is_final: true,
}

describe('visual artifact payload validation', () => {
  it('converts a valid backend payload to the stable frontend shape', () => {
    expect(parseVisualArtifactMessage(validArtifact)).toMatchObject({ artifactId: 'budget', kind: 'dashboard', revision: 1 })
  })

  it('rejects unknown kinds and source HTML above the UTF-8 byte limit', () => {
    expect(parseVisualArtifactMessage({ ...validArtifact, kind: 'video' })).toBeNull()
    expect(parseVisualArtifactMessage({ ...validArtifact, source_html: 'é'.repeat(100_001) })).toBeNull()
  })

  it('parses bounded motion soundtrack cues into the frontend contract', () => {
    const motion = {
      ...validArtifact,
      kind: 'motion',
      duration_ms: 2_000,
      soundtrack: {
        style: 'restrained tactile pulses',
        cues: [{ id: 'intake-hit', start_ms: 400, duration_ms: 180, waveform: 'triangle', frequency_hz: 440, gain: 0.12 }],
      },
    }
    expect(parseVisualArtifactMessage(motion)?.soundtrack).toEqual({
      style: 'restrained tactile pulses',
      cues: [{ id: 'intake-hit', startMs: 400, durationMs: 180, waveform: 'triangle', frequencyHz: 440, gain: 0.12 }],
    })
  })

  it('rejects soundtrack cues beyond the motion duration or on static artifacts', () => {
    const motion = {
      ...validArtifact,
      kind: 'motion',
      duration_ms: 1_000,
      soundtrack: {
        style: 'pulses',
        cues: [{ id: 'late-hit', start_ms: 950, duration_ms: 100, waveform: 'sine', frequency_hz: 440, gain: 0.1 }],
      },
    }
    expect(parseVisualArtifactMessage(motion)).toBeNull()
    expect(parseVisualArtifactMessage({ ...validArtifact, soundtrack: motion.soundtrack })).toBeNull()
  })

  it('accepts only bounded bridge messages', () => {
    expect(parseVisualArtifactBridgeMessage({ type: 'send_prompt', prompt: 'Refresh dashboard' })).toEqual({ type: 'send_prompt', prompt: 'Refresh dashboard' })
    expect(parseVisualArtifactBridgeMessage({ type: 'send_prompt', prompt: 'x'.repeat(10_001) })).toBeNull()
    expect(parseVisualArtifactBridgeMessage({ type: 'resize', height: 1_000_000 })).toBeNull()
  })

  it('accepts a bounded motion timeline and strips untrusted extra fields', () => {
    expect(parseVisualArtifactBridgeMessage({
      type: 'timeline',
      beats: [{
        id: 'opening', title: 'Collect rainwater', startFrame: 0, endFrame: 89,
        markers: [{ frame: 40, kind: 'hit' }], untrusted: 'ignored',
      }],
    })).toEqual({
      type: 'timeline',
      beats: [{ id: 'opening', title: 'Collect rainwater', startFrame: 0, endFrame: 89, markers: [{ frame: 40, kind: 'hit' }] }],
    })
  })

  it('rejects malformed or oversized motion timelines', () => {
    const beat = { id: 'opening', title: 'Opening', startFrame: 0, endFrame: 89, markers: [] }
    const parse = (beats: unknown) => parseVisualArtifactBridgeMessage({ type: 'timeline', beats })

    expect(parse([{ ...beat }, { ...beat }])).toBeNull()
    expect(parse(Array.from({ length: 65 }, (_, index) => ({ ...beat, id: `beat-${index}` })))).toBeNull()
    expect(parse([{ ...beat, startFrame: -1 }])).toBeNull()
    expect(parse([{ ...beat, startFrame: 90, endFrame: 89 }])).toBeNull()
    expect(parse([{ ...beat, markers: [{ frame: 90, kind: 'cut' }] }])).toBeNull()
    expect(parse([{ ...beat, title: 'x'.repeat(121) }])).toBeNull()
    expect(parse([{ ...beat, id: 'opening', markers: Array.from({ length: 33 }, () => ({ frame: 1, kind: 'hit' })) }])).toBeNull()
  })
})
