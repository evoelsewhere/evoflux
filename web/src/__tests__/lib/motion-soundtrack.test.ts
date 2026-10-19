import { afterEach, describe, expect, it, vi } from 'vitest'
import { synthesizeMotionSoundtrack } from '@/lib/motion-soundtrack'
import type { MotionSoundtrackSpec } from '@/api/types'

class FakeAudioBuffer {
  readonly sampleRate: number
  readonly length: number
  readonly duration: number
  private readonly samples: Float32Array[]

  constructor(options: { numberOfChannels: number; length: number; sampleRate: number }) {
    this.sampleRate = options.sampleRate
    this.length = options.length
    this.duration = options.length / options.sampleRate
    this.samples = Array.from({ length: options.numberOfChannels }, () => new Float32Array(options.length))
  }

  getChannelData(channel: number) {
    return this.samples[channel]!
  }
}

const cue: MotionSoundtrackSpec = {
  style: 'restrained tactile pulses',
  cues: [{ id: 'intake-hit', startMs: 250, durationMs: 200, waveform: 'triangle', frequencyHz: 440, gain: 0.12 }],
}

afterEach(() => vi.unstubAllGlobals())

describe('motion soundtrack synthesis', () => {
  it('creates a deterministic bounded buffer with the declared cue timing', async () => {
    vi.stubGlobal('AudioBuffer', FakeAudioBuffer)
    const first = await synthesizeMotionSoundtrack(cue, 1_000)
    const second = await synthesizeMotionSoundtrack(cue, 1_000)
    expect(first).not.toBeNull()
    expect(first?.duration).toBe(1)
    expect(first?.length).toBe(48_000)
    const samples = first!.getChannelData(0)
    expect(samples.slice(0, 12_000).every((sample) => sample === 0)).toBe(true)
    expect(samples.slice(12_000, 21_600).some((sample) => sample !== 0)).toBe(true)
    expect(samples.slice(21_600).every((sample) => sample === 0)).toBe(true)
    expect(Math.max(...samples.slice(0, 24_000).map(Math.abs))).toBeLessThanOrEqual(0.95)
    expect([...samples]).toEqual([...second!.getChannelData(0)])
  })

  it('uses seeded noise and returns null when no cues were requested', async () => {
    vi.stubGlobal('AudioBuffer', FakeAudioBuffer)
    const noise: MotionSoundtrackSpec = {
      style: 'soft air',
      cues: [{ id: 'air', startMs: 0, durationMs: 100, waveform: 'noise', frequencyHz: 200, gain: 0.05 }],
    }
    const first = await synthesizeMotionSoundtrack(noise, 200)
    const second = await synthesizeMotionSoundtrack(noise, 200)
    expect(first).not.toBeNull()
    expect([...first!.getChannelData(0)]).toEqual([...second!.getChannelData(0)])
    expect(await synthesizeMotionSoundtrack({ style: 'silent', cues: [] }, 200)).toBeNull()
  })

  it('stops synthesis when the video job is cancelled', async () => {
    vi.stubGlobal('AudioBuffer', FakeAudioBuffer)
    const timer = vi.spyOn(window, 'setTimeout').mockImplementation(((callback: TimerHandler) => {
      if (typeof callback === 'function') callback()
      return 1
    }) as typeof window.setTimeout)
    await expect(synthesizeMotionSoundtrack(cue, 1_000, { isCancelled: () => true }))
      .rejects.toMatchObject({ name: 'AbortError' })
    expect(timer).not.toHaveBeenCalled()
  })
})
