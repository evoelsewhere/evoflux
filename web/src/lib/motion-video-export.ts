import {
  BufferTarget,
  CanvasSource,
  getEncodableVideoCodecs,
  Mp4OutputFormat,
  Output,
  QUALITY_HIGH,
  WebMOutputFormat,
} from 'mediabunny'

const FPS = 30
const MAX_OUTPUT_BYTES = 150_000_000
const MAX_WIDTH = 1280
const MAX_HEIGHT = 720

export interface RenderedMotionFrame {
  requestId: number
  bitmap: ImageBitmap
}

export interface MotionVideoExportOptions {
  durationMs: number
  canvasWidth: number
  canvasHeight: number
  requestFrame: (currentTimeMs: number, requestId: number) => Promise<RenderedMotionFrame>
  isCancelled: () => boolean
  onProgress: (framesRendered: number, totalFrames: number) => void
}

export interface MotionVideoExportResult {
  blob: Blob
  extension: 'mp4' | 'webm'
  frameCount: number
}

export function canRenderMotionFrames(): boolean {
  return typeof VideoEncoder !== 'undefined'
    && typeof ImageBitmap !== 'undefined'
    && typeof createImageBitmap === 'function'
}

/** Seek the sandboxed composition once per timestamp, then encode that exact canvas state. */
export async function exportMotionFrames(options: MotionVideoExportOptions): Promise<MotionVideoExportResult> {
  const { durationMs, canvasWidth, canvasHeight } = options
  if (!Number.isInteger(durationMs) || durationMs < 1 || durationMs > 120_000) {
    throw new Error('The motion duration is outside the supported range.')
  }
  if (!Number.isInteger(canvasWidth) || !Number.isInteger(canvasHeight) || canvasWidth < 1 || canvasHeight < 1) {
    throw new Error('The motion canvas has invalid dimensions.')
  }

  const supportedCodecs = await getEncodableVideoCodecs()
  const codec = (['avc', 'vp9', 'vp8'] as const).find((candidate) => supportedCodecs.includes(candidate))
  if (!codec) throw new Error('This browser has no supported video encoder for frame export.')

  const format = codec === 'avc' ? new Mp4OutputFormat() : new WebMOutputFormat()
  const target = new BufferTarget()
  const output = new Output({ format, target })
  const scale = Math.min(1, MAX_WIDTH / canvasWidth, MAX_HEIGHT / canvasHeight)
  const width = Math.max(2, Math.floor((canvasWidth * scale) / 2) * 2)
  const height = Math.max(2, Math.floor((canvasHeight * scale) / 2) * 2)
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d', { alpha: false })
  if (!context) throw new Error('The video encoder could not create a canvas.')

  const source = new CanvasSource(canvas, { codec, quality: QUALITY_HIGH })
  output.addVideoTrack(source, { frameRate: FPS })

  const totalFrames = Math.ceil((durationMs / 1000) * FPS)
  let finalized = false
  let lastProgress = -1

  try {
    await output.start()
    for (let frameIndex = 0; frameIndex < totalFrames; frameIndex += 1) {
      if (options.isCancelled()) throw new DOMException('Video export cancelled.', 'AbortError')

      const requestId = frameIndex + 1
      const currentTimeMs = Math.min(durationMs, (frameIndex / FPS) * 1000)
      const frame = await options.requestFrame(currentTimeMs, requestId)
      if (frame.requestId !== requestId) {
        frame.bitmap.close()
        throw new Error('The motion renderer returned a stale frame.')
      }
      try {
        context.clearRect(0, 0, width, height)
        context.drawImage(frame.bitmap, 0, 0, width, height)
      } finally {
        frame.bitmap.close()
      }

      await source.add(frameIndex / FPS, 1 / FPS)
      const percent = Math.floor(((frameIndex + 1) / totalFrames) * 20)
      if (percent !== lastProgress) {
        lastProgress = percent
        options.onProgress(frameIndex + 1, totalFrames)
      }
    }

    await output.finalize()
    finalized = true
    const buffer = target.buffer
    if (!buffer) throw new Error('The video encoder returned an empty file.')
    if (buffer.byteLength > MAX_OUTPUT_BYTES) {
      throw new Error('The video exceeded the 150 MB export limit. Try a shorter animation.')
    }
    options.onProgress(totalFrames, totalFrames)
    const extension = codec === 'avc' ? 'mp4' : 'webm'
    return {
      blob: new Blob([buffer], { type: format.mimeType }),
      extension,
      frameCount: totalFrames,
    }
  } catch (error) {
    if (!finalized && (output.state === 'pending' || output.state === 'started')) {
      await output.cancel().catch(() => undefined)
    }
    throw error
  }
}
