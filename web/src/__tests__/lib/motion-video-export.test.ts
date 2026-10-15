import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getMotionExportDimensions, exportMotionFrames } from '@/lib/motion-video-export'
import { getEncodableAudioCodecs } from 'mediabunny'
import { synthesizeMotionSoundtrack } from '@/lib/motion-soundtrack'

const encoderMocks = vi.hoisted(() => ({
  add: vi.fn(),
  start: vi.fn(),
  finalize: vi.fn(),
  cancel: vi.fn(),
  addAudio: vi.fn(),
  audioTrack: { kind: 'audio' },
}))

vi.mock('@/lib/motion-soundtrack', () => ({
  MOTION_AUDIO_SAMPLE_RATE: 48_000,
  synthesizeMotionSoundtrack: vi.fn(async () => ({ duration: 0.1, sampleRate: 48_000 })),
}))

vi.mock('mediabunny', () => ({
  BufferTarget: class { buffer = new ArrayBuffer(1) },
  CanvasSource: class { add = encoderMocks.add },
  AudioBufferSource: class { add = encoderMocks.addAudio },
  getEncodableAudioCodecs: vi.fn(async () => ['aac', 'opus']),
  getEncodableVideoCodecs: vi.fn(async () => ['avc']),
  Mp4OutputFormat: class { mimeType = 'video/mp4'; getSupportedAudioCodecs() { return ['aac'] } },
  Output: class {
    state = 'pending'
    tracks: unknown[] = []
    addVideoTrack = vi.fn(() => { const track = { kind: 'video' }; this.tracks.push(track); return track })
    addAudioTrack = vi.fn(() => { this.tracks.push(encoderMocks.audioTrack); return encoderMocks.audioTrack })
    async start() { this.state = 'started'; await encoderMocks.start() }
    async finalize() { this.state = 'finalized'; await encoderMocks.finalize() }
    async cancel() { this.state = 'cancelled'; await encoderMocks.cancel() }
  },
  QUALITY_HIGH: 1,
  QUALITY_MEDIUM: 0.7,
  WebMOutputFormat: class { mimeType = 'video/webm'; getSupportedAudioCodecs() { return ['opus'] } },
}))

beforeEach(() => vi.clearAllMocks())
afterEach(() => vi.unstubAllGlobals())

describe('motion export dimensions', () => {
  it('keeps the source aspect ratio within the selected quality preset', () => {
    expect(getMotionExportDimensions(1920, 1080, 'balanced')).toEqual({ width: 1280, height: 720 })
    expect(getMotionExportDimensions(1920, 1080, 'high')).toEqual({ width: 1920, height: 1080 })
  })

  it('does not upscale small canvases and rounds output to encoder-safe even dimensions', () => {
    expect(getMotionExportDimensions(801, 601, 'high')).toEqual({ width: 800, height: 600 })
    expect(getMotionExportDimensions(320, 180, 'high')).toEqual({ width: 320, height: 180 })
  })

  it('reports each completed frame exactly once, including the final frame', async () => {
    const context = { clearRect: vi.fn(), drawImage: vi.fn() }
    vi.spyOn(document, 'createElement').mockImplementation(((tagName: string) => {
      if (tagName !== 'canvas') return document.createElementNS('http://www.w3.org/1999/xhtml', tagName) as HTMLElement
      return { width: 0, height: 0, getContext: () => context } as unknown as HTMLCanvasElement
    }) as typeof document.createElement)
    const progress: Array<[number, number]> = []

    await exportMotionFrames({
      durationMs: 100,
      canvasWidth: 640,
      canvasHeight: 360,
      preset: 'balanced',
      isCancelled: () => false,
      onProgress: (completed, total) => progress.push([completed, total]),
      requestFrame: async (_time, requestId) => ({
        requestId,
        bitmap: { close: vi.fn() } as unknown as ImageBitmap,
      }),
    })

    expect(progress).toEqual([[1, 3], [2, 3], [3, 3]])
  })

  it('stops before requesting another frame after cancellation and closes the current bitmap', async () => {
    const context = { clearRect: vi.fn(), drawImage: vi.fn() }
    vi.spyOn(document, 'createElement').mockImplementation(((tagName: string) => (
      tagName === 'canvas'
        ? { width: 0, height: 0, getContext: () => context } as unknown as HTMLCanvasElement
        : document.createElementNS('http://www.w3.org/1999/xhtml', tagName) as HTMLElement
    )) as typeof document.createElement)
    const bitmap = { close: vi.fn() } as unknown as ImageBitmap
    const requestFrame = vi.fn(async (_time: number, requestId: number) => ({ requestId, bitmap }))
    let cancelled = false

    await expect(exportMotionFrames({
      durationMs: 100,
      canvasWidth: 640,
      canvasHeight: 360,
      preset: 'balanced',
      isCancelled: () => cancelled,
      onProgress: () => { cancelled = true },
      requestFrame,
    })).rejects.toMatchObject({ name: 'AbortError' })

    expect(requestFrame).toHaveBeenCalledTimes(1)
    expect(bitmap.close).toHaveBeenCalledTimes(1)
    expect(encoderMocks.cancel).toHaveBeenCalledTimes(1)
  })

  it('adds a synthesized audio track before finalization and reports it included only after success', async () => {
    vi.mocked(synthesizeMotionSoundtrack).mockResolvedValueOnce({ duration: 0.1, sampleRate: 48_000 } as AudioBuffer)
    const status: string[] = []
    const context = { clearRect: vi.fn(), drawImage: vi.fn() }
    vi.spyOn(document, 'createElement').mockImplementation(((tagName: string) => (
      tagName === 'canvas'
        ? { width: 0, height: 0, getContext: () => context } as unknown as HTMLCanvasElement
        : document.createElementNS('http://www.w3.org/1999/xhtml', tagName) as HTMLElement
    )) as typeof document.createElement)

    const result = await exportMotionFrames({
      durationMs: 100, canvasWidth: 640, canvasHeight: 360, preset: 'balanced',
      isCancelled: () => false, onProgress: () => {},
      requestFrame: async (_time, requestId) => ({ requestId, bitmap: { close: vi.fn() } as unknown as ImageBitmap }),
      soundtrack: { style: 'tactile', cues: [{ id: 'hit', startMs: 0, durationMs: 100, waveform: 'sine', frequencyHz: 440, gain: 0.1 }] },
      onAudioStatus: (value) => status.push(value),
    })

    expect(encoderMocks.addAudio).toHaveBeenCalledTimes(1)
    expect(encoderMocks.addAudio.mock.invocationCallOrder[0]).toBeLessThan(encoderMocks.finalize.mock.invocationCallOrder[0]!)
    expect(result.audioStatus).toBe('included')
    expect(status).toContain('rendering')
    expect(status.at(-1)).toBe('included')
  })

  it('keeps video export valid but marks requested audio unavailable when no compatible encoder exists', async () => {
    vi.mocked(getEncodableAudioCodecs).mockResolvedValueOnce([])
    const context = { clearRect: vi.fn(), drawImage: vi.fn() }
    vi.spyOn(document, 'createElement').mockImplementation(((tagName: string) => (
      tagName === 'canvas'
        ? { width: 0, height: 0, getContext: () => context } as unknown as HTMLCanvasElement
        : document.createElementNS('http://www.w3.org/1999/xhtml', tagName) as HTMLElement
    )) as typeof document.createElement)
    const status: string[] = []

    const result = await exportMotionFrames({
      durationMs: 100, canvasWidth: 640, canvasHeight: 360, preset: 'balanced',
      isCancelled: () => false, onProgress: () => {},
      requestFrame: async (_time, requestId) => ({ requestId, bitmap: { close: vi.fn() } as unknown as ImageBitmap }),
      soundtrack: { style: 'tactile', cues: [{ id: 'hit', startMs: 0, durationMs: 100, waveform: 'sine', frequencyHz: 440, gain: 0.1 }] },
      onAudioStatus: (value) => status.push(value),
    })

    expect(result.blob).toBeInstanceOf(Blob)
    expect(result.audioStatus).toBe('unavailable')
    expect(status).not.toContain('included')
    expect(synthesizeMotionSoundtrack).not.toHaveBeenCalled()
  })

  it('retries video-only when the audio encoder rejects the synthesized track', async () => {
    vi.mocked(synthesizeMotionSoundtrack).mockResolvedValueOnce({ duration: 0.1, sampleRate: 48_000 } as AudioBuffer)
    encoderMocks.addAudio.mockRejectedValueOnce(new Error('Audio encoder failed'))
    const context = { clearRect: vi.fn(), drawImage: vi.fn() }
    vi.spyOn(document, 'createElement').mockImplementation(((tagName: string) => (
      tagName === 'canvas'
        ? { width: 0, height: 0, getContext: () => context } as unknown as HTMLCanvasElement
        : document.createElementNS('http://www.w3.org/1999/xhtml', tagName) as HTMLElement
    )) as typeof document.createElement)
    const status: string[] = []

    const result = await exportMotionFrames({
      durationMs: 100, canvasWidth: 640, canvasHeight: 360, preset: 'balanced',
      isCancelled: () => false, onProgress: () => {},
      requestFrame: async (_time, requestId) => ({ requestId, bitmap: { close: vi.fn() } as unknown as ImageBitmap }),
      soundtrack: { style: 'tactile', cues: [{ id: 'hit', startMs: 0, durationMs: 100, waveform: 'sine', frequencyHz: 440, gain: 0.1 }] },
      onAudioStatus: (value) => status.push(value),
    })

    expect(result.blob).toBeInstanceOf(Blob)
    expect(result.audioStatus).toBe('unavailable')
    expect(encoderMocks.cancel).toHaveBeenCalledTimes(1)
    expect(status).not.toContain('included')
  })
})
