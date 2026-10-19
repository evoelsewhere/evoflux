import {
  BufferTarget,
  CanvasSource,
  AudioBufferSource,
  getEncodableAudioCodecs,
  getEncodableVideoCodecs,
  Mp4OutputFormat,
  Output,
  QUALITY_HIGH,
  QUALITY_MEDIUM,
  WebMOutputFormat,
} from 'mediabunny'
import type { AudioCodec } from 'mediabunny'
import type { MotionSoundtrackSpec } from '@/api/types'
import { MOTION_AUDIO_SAMPLE_RATE, synthesizeMotionSoundtrack } from '@/lib/motion-soundtrack'

const FPS = 30
const MAX_OUTPUT_BYTES = 150_000_000

export type MotionExportPreset = 'balanced' | 'high'

const PRESET_LIMITS: Record<MotionExportPreset, { maxWidth: number; maxHeight: number }> = {
  balanced: { maxWidth: 1280, maxHeight: 720 },
  high: { maxWidth: 1920, maxHeight: 1080 },
}

export function getMotionExportDimensions(
  canvasWidth: number,
  canvasHeight: number,
  preset: MotionExportPreset,
): { width: number; height: number } {
  const { maxWidth, maxHeight } = PRESET_LIMITS[preset]
  const scale = Math.min(1, maxWidth / canvasWidth, maxHeight / canvasHeight)
  return {
    width: Math.max(2, Math.floor((canvasWidth * scale) / 2) * 2),
    height: Math.max(2, Math.floor((canvasHeight * scale) / 2) * 2),
  }
}

export interface RenderedMotionFrame {
  requestId: number
  bitmap: ImageBitmap
}

export interface MotionVideoExportOptions {
  durationMs: number
  canvasWidth: number
  canvasHeight: number
  preset: MotionExportPreset
  requestFrame: (currentTimeMs: number, requestId: number) => Promise<RenderedMotionFrame>
  isCancelled: () => boolean
  onProgress: (framesRendered: number, totalFrames: number) => void
  onRenderedFrame?: (frame: { frameIndex: number; totalFrames: number; currentTimeMs: number; bitmap: ImageBitmap }) => void | Promise<void>
  soundtrack?: MotionSoundtrackSpec | null
  onAudioStatus?: (status: 'not_requested' | 'unavailable' | 'rendering' | 'included') => void
}

export interface MotionVideoExportResult {
  blob: Blob
  extension: 'mp4' | 'webm'
  frameCount: number
  audioStatus: 'not_requested' | 'unavailable' | 'included'
}

async function awaitWithCancellation<T>(promise: Promise<T>, isCancelled: () => boolean): Promise<T> {
  if (isCancelled()) throw new DOMException('Video export cancelled.', 'AbortError')
  let interval: number | undefined
  const cancellation = new Promise<never>((_resolve, reject) => {
    interval = window.setInterval(() => {
      if (isCancelled()) reject(new DOMException('Video export cancelled.', 'AbortError'))
    }, 25)
  })
  try {
    return await Promise.race([promise, cancellation])
  } finally {
    if (interval !== undefined) window.clearInterval(interval)
  }
}

export function canRenderMotionFrames(): boolean {
  return typeof VideoEncoder !== 'undefined'
    && typeof ImageBitmap !== 'undefined'
    && typeof createImageBitmap === 'function'
}

/** Seek the sandboxed composition once per timestamp, then encode that exact canvas state. */
export async function exportMotionFrames(options: MotionVideoExportOptions): Promise<MotionVideoExportResult> {
  const { durationMs, canvasWidth, canvasHeight, preset } = options
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
  const { width, height } = getMotionExportDimensions(canvasWidth, canvasHeight, preset)
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d', { alpha: false })
  if (!context) throw new Error('The video encoder could not create a canvas.')

  const totalFrames = Math.ceil((durationMs / 1000) * FPS)
  const soundtrack = options.soundtrack
  const hasRequestedSound = Boolean(soundtrack?.cues.length)
  let audioStatus: 'not_requested' | 'unavailable' | 'rendering' | 'included' = hasRequestedSound
    ? 'unavailable'
    : 'not_requested'
  let audioBuffer: AudioBuffer | null = null
  let audioCodec: AudioCodec | null = null
  if (hasRequestedSound && soundtrack) {
    audioStatus = 'rendering'
    options.onAudioStatus?.(audioStatus)
    try {
      const encodableAudioCodecs = await getEncodableAudioCodecs(
        format.getSupportedAudioCodecs(),
        { numberOfChannels: 1, sampleRate: MOTION_AUDIO_SAMPLE_RATE, quality: QUALITY_MEDIUM },
      )
      audioCodec = encodableAudioCodecs[0] ?? null
      if (!audioCodec) {
        audioStatus = 'unavailable'
      } else {
        audioBuffer = await synthesizeMotionSoundtrack(soundtrack, durationMs, {
          isCancelled: options.isCancelled,
        })
        if (!audioBuffer) {
          audioStatus = 'unavailable'
          audioCodec = null
        }
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error
      audioStatus = 'unavailable'
      audioBuffer = null
      audioCodec = null
    }
    options.onAudioStatus?.(audioStatus)
  }

  const makeOutput = (includeAudio: boolean) => {
    const target = new BufferTarget()
    const output = new Output({ format, target })
    const source = new CanvasSource(canvas, { codec, quality: preset === 'high' ? QUALITY_HIGH : QUALITY_MEDIUM })
    output.addVideoTrack(source, { frameRate: FPS })
    const audioSource = includeAudio && audioCodec
      ? new AudioBufferSource({ codec: audioCodec, quality: QUALITY_MEDIUM })
      : null
    const audioTrack = audioSource ? output.addAudioTrack(audioSource) : null
    return { target, output, source, audioSource, audioTrack }
  }

  let bundle: ReturnType<typeof makeOutput>
  try {
    bundle = makeOutput(Boolean(audioBuffer && audioCodec))
  } catch (error) {
    if (!audioBuffer || !audioCodec) throw error
    audioStatus = 'unavailable'
    audioBuffer = null
    audioCodec = null
    options.onAudioStatus?.(audioStatus)
    bundle = makeOutput(false)
  }
  let audioSamplesWritten = false
  let finalized = false

  try {
    try {
      await bundle.output.start()
      if (bundle.audioSource && audioBuffer) {
        await awaitWithCancellation(bundle.audioSource.add(audioBuffer), options.isCancelled)
        audioSamplesWritten = true
      }
    } catch (error) {
      if (!bundle.audioTrack) throw error
      if (error instanceof DOMException && error.name === 'AbortError') throw error
      await bundle.output.cancel().catch(() => undefined)
      if (options.isCancelled()) throw new DOMException('Video export cancelled.', 'AbortError')
      audioStatus = 'unavailable'
      audioBuffer = null
      audioCodec = null
      options.onAudioStatus?.(audioStatus)
      bundle = makeOutput(false)
      await bundle.output.start()
    }
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
        await awaitWithCancellation(bundle.source.add(frameIndex / FPS, 1 / FPS), options.isCancelled)
        await options.onRenderedFrame?.({
          frameIndex,
          totalFrames,
          currentTimeMs,
          bitmap: frame.bitmap,
        })
      } finally {
        frame.bitmap.close()
      }
      options.onProgress(frameIndex + 1, totalFrames)
    }

    await awaitWithCancellation(bundle.output.finalize(), options.isCancelled)
    finalized = true
    if (audioSamplesWritten && bundle.audioTrack && bundle.output.tracks.includes(bundle.audioTrack)) {
      audioStatus = 'included'
    } else if (hasRequestedSound) {
      audioStatus = 'unavailable'
    }
    const finalAudioStatus = audioStatus === 'rendering'
      ? hasRequestedSound ? 'unavailable' : 'not_requested'
      : audioStatus
    options.onAudioStatus?.(finalAudioStatus)
    const buffer = bundle.target.buffer
    if (!buffer) throw new Error('The video encoder returned an empty file.')
    if (buffer.byteLength > MAX_OUTPUT_BYTES) {
      throw new Error('The video exceeded the 150 MB export limit. Try a shorter animation.')
    }
    const extension = codec === 'avc' ? 'mp4' : 'webm'
    return {
      blob: new Blob([buffer], { type: format.mimeType }),
      extension,
      frameCount: totalFrames,
      audioStatus: finalAudioStatus,
    }
  } catch (error) {
    if (!finalized && (bundle.output.state === 'pending' || bundle.output.state === 'started')) {
      await bundle.output.cancel().catch(() => undefined)
    }
    throw error
  }
}
