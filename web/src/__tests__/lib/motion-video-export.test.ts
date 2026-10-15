import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getMotionExportDimensions, exportMotionFrames } from '@/lib/motion-video-export'

const encoderMocks = vi.hoisted(() => ({
  add: vi.fn(),
  start: vi.fn(),
  finalize: vi.fn(),
  cancel: vi.fn(),
}))

vi.mock('mediabunny', () => ({
  BufferTarget: class { buffer = new ArrayBuffer(1) },
  CanvasSource: class { add = encoderMocks.add },
  getEncodableVideoCodecs: vi.fn(async () => ['avc']),
  Mp4OutputFormat: class { mimeType = 'video/mp4' },
  Output: class {
    state = 'pending'
    addVideoTrack = vi.fn()
    async start() { this.state = 'started'; await encoderMocks.start() }
    async finalize() { this.state = 'finalized'; await encoderMocks.finalize() }
    async cancel() { this.state = 'cancelled'; await encoderMocks.cancel() }
  },
  QUALITY_HIGH: 1,
  QUALITY_MEDIUM: 0.7,
  WebMOutputFormat: class { mimeType = 'video/webm' },
}))

beforeEach(() => vi.clearAllMocks())

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
})
