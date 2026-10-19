import type { MotionSoundCue, MotionSoundtrackSpec } from '@/api/types'

export const MOTION_AUDIO_SAMPLE_RATE = 48_000
const AUDIO_BLOCK_FRAMES = 24_000
const MAX_MIX_AMPLITUDE = 0.95

export interface MotionSoundSynthesisOptions {
  isCancelled?: () => boolean
}

function validateSpec(spec: MotionSoundtrackSpec, durationMs: number): void {
  if (!Number.isSafeInteger(durationMs) || durationMs < 1 || durationMs > 120_000) {
    throw new Error('The motion soundtrack duration is outside the supported range.')
  }
  if (!spec || typeof spec.style !== 'string' || !spec.style.trim() || spec.style.length > 80
    || !Array.isArray(spec.cues) || spec.cues.length > 64) {
    throw new Error('The motion soundtrack specification is invalid.')
  }
  const ids = new Set<string>()
  for (const cue of spec.cues) {
    if (!cue || !/^[a-z0-9][a-z0-9_-]{0,63}$/.test(cue.id) || ids.has(cue.id)
      || !Number.isSafeInteger(cue.startMs) || cue.startMs < 0
      || !Number.isSafeInteger(cue.durationMs) || cue.durationMs < 20 || cue.durationMs > 10_000
      || cue.startMs + cue.durationMs > durationMs
      || !['sine', 'triangle', 'square', 'sawtooth', 'noise'].includes(cue.waveform)
      || !Number.isFinite(cue.frequencyHz) || cue.frequencyHz < 30 || cue.frequencyHz > 12_000
      || !Number.isFinite(cue.gain) || cue.gain < 0 || cue.gain > 0.35) {
      throw new Error('The motion soundtrack contains an invalid sound cue.')
    }
    ids.add(cue.id)
  }
}

function seedFor(value: string): number {
  let hash = 2_166_136_261
  for (let index = 0; index < value.length; index += 1) {
    hash = Math.imul(hash ^ value.charCodeAt(index), 16_777_619)
  }
  return (hash >>> 0) || 1
}

function waveformSample(cue: MotionSoundCue, frame: number, random: { value: number }): number {
  if (cue.waveform === 'noise') {
    random.value = (Math.imul(random.value, 1_664_525) + 1_013_904_223) >>> 0
    return (random.value / 0xffff_ffff) * 2 - 1
  }
  const phase = (cue.frequencyHz * frame / MOTION_AUDIO_SAMPLE_RATE) % 1
  if (cue.waveform === 'triangle') return 1 - 4 * Math.abs(Math.round(phase) - phase)
  if (cue.waveform === 'square') return phase < 0.5 ? 1 : -1
  if (cue.waveform === 'sawtooth') return phase * 2 - 1
  return Math.sin(phase * Math.PI * 2)
}

function envelope(cue: MotionSoundCue, frame: number): number {
  const seconds = frame / MOTION_AUDIO_SAMPLE_RATE
  const durationSeconds = cue.durationMs / 1000
  const attackSeconds = Math.min(0.012, durationSeconds / 4)
  const releaseSeconds = Math.min(0.08, durationSeconds / 3)
  return Math.min(
    1,
    seconds / attackSeconds,
    (durationSeconds - seconds) / releaseSeconds,
  )
}

/** Synthesize sparse deterministic cues into a mono AudioBuffer for local muxing. */
export async function synthesizeMotionSoundtrack(
  spec: MotionSoundtrackSpec,
  durationMs: number,
  options: MotionSoundSynthesisOptions = {},
): Promise<AudioBuffer | null> {
  validateSpec(spec, durationMs)
  if (spec.cues.length === 0) return null
  if (typeof AudioBuffer === 'undefined') return null

  const length = Math.ceil(durationMs * MOTION_AUDIO_SAMPLE_RATE / 1000)
  let buffer: AudioBuffer
  try {
    buffer = new AudioBuffer({ numberOfChannels: 1, length, sampleRate: MOTION_AUDIO_SAMPLE_RATE })
  } catch {
    return null
  }
  const samples = buffer.getChannelData(0)
  const randomStates = spec.cues.map((cue) => ({ value: seedFor(cue.id) }))

  for (let blockStart = 0; blockStart < length; blockStart += AUDIO_BLOCK_FRAMES) {
    if (options.isCancelled?.()) throw new DOMException('Motion soundtrack synthesis cancelled.', 'AbortError')
    const blockEnd = Math.min(length, blockStart + AUDIO_BLOCK_FRAMES)
    for (let cueIndex = 0; cueIndex < spec.cues.length; cueIndex += 1) {
      const cue = spec.cues[cueIndex]!
      const cueStart = Math.floor(cue.startMs * MOTION_AUDIO_SAMPLE_RATE / 1000)
      const cueEnd = Math.min(length, Math.ceil((cue.startMs + cue.durationMs) * MOTION_AUDIO_SAMPLE_RATE / 1000))
      const start = Math.max(blockStart, cueStart)
      const end = Math.min(blockEnd, cueEnd)
      if (start >= end || cue.gain === 0) continue
      const random = randomStates[cueIndex]!
      for (let index = start; index < end; index += 1) {
        const localFrame = index - cueStart
        samples[index] += waveformSample(cue, localFrame, random) * cue.gain * envelope(cue, localFrame)
      }
    }
    for (let index = blockStart; index < blockEnd; index += 1) {
      samples[index] = Math.max(-MAX_MIX_AMPLITUDE, Math.min(MAX_MIX_AMPLITUDE, samples[index]!))
    }
    if (blockEnd < length) await new Promise<void>((resolve) => window.setTimeout(resolve, 0))
  }
  if (options.isCancelled?.()) throw new DOMException('Motion soundtrack synthesis cancelled.', 'AbortError')
  return buffer
}
