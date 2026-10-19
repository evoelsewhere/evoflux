import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import type { VisualArtifactPayload } from '@/api/types'
import type { ThemePreference } from '@/lib/theme'
import { VisualArtifactFrame } from '@/components/VisualArtifactFrame'
import { SelectControl } from '@/components/ui/select'
import { canRenderMotionFrames, getSupportedExportMimeType } from '@/lib/visual-artifact-export'
import type { MotionTimelineBeat, VisualArtifactBridgeMessage } from '@/lib/visual-artifact-bridge'
import type { MotionExportPreset } from '@/lib/motion-video-export'
import {
  getMotionRenderSnapshot,
  publishMotionRenderSnapshot,
  subscribeMotionRender,
  type MotionRenderSnapshot,
  type MotionReviewSample,
  type MotionReviewSampleRole,
  type MotionAudioStatus,
} from '@/lib/motion-render-store'
import type { MotionReviewRequest } from '@/stores/useUIStore'
import type { MotionSampleReviewRequest } from '@/stores/useUIStore'
import { postMotionReviewSamples } from '@/api/client/team'

type PendingFrame = {
  requestId: number
  resolve: (frame: { requestId: number; bitmap: ImageBitmap }) => void
  reject: (error: Error) => void
  timeoutId: number
}

const MOTION_FPS = 30
const MAX_REVIEW_SAMPLES = 12
let motionRenderSequence = 0

function representativeFrames(beats: MotionTimelineBeat[], totalFrames: number): Array<{ frameIndex: number; beatId: string; role: MotionReviewSampleRole }> {
  const lastFrame = Math.max(0, totalFrames - 1)
  const selected = new Map<number, { frameIndex: number; beatId: string; role: MotionReviewSampleRole }>()
  const add = (frameIndex: number, beatId: string, role: MotionReviewSampleRole) => {
    const bounded = Math.max(0, Math.min(lastFrame, frameIndex))
    if (!selected.has(bounded)) selected.set(bounded, { frameIndex: bounded, beatId, role })
  }

  if (beats.length === 0) {
    add(0, 'sequence', 'style')
    add(Math.floor(lastFrame / 2), 'sequence', 'key_state')
    add(lastFrame, 'sequence', 'key_state')
  } else {
    for (const beat of beats) {
      add(beat.startFrame, beat.id, 'key_state')
      for (const marker of beat.markers) {
        if (marker.kind === 'hit') add(marker.frame, beat.id, 'impact')
        else {
          add(marker.frame - 1, beat.id, 'before_transition')
          add(marker.frame, beat.id, 'after_transition')
        }
      }
      if (selected.size >= MAX_REVIEW_SAMPLES) break
    }
  }
  if (selected.size === 0) {
    add(0, 'sequence', 'style')
    add(lastFrame, 'sequence', 'key_state')
  }
  return [...selected.values()].slice(0, MAX_REVIEW_SAMPLES)
}

async function bitmapToPreviewUrl(bitmap: ImageBitmap): Promise<string | null> {
  const scale = Math.min(1, 320 / bitmap.width, 180 / bitmap.height)
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(bitmap.width * scale))
  canvas.height = Math.max(1, Math.round(bitmap.height * scale))
  const context = canvas.getContext('2d')
  if (!context) return null
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.78))
  if (!blob || blob.size > 200_000) return null
  return URL.createObjectURL(blob)
}

async function bitmapToReviewBlob(bitmap: ImageBitmap): Promise<Blob | null> {
  let scale = Math.min(1, 640 / bitmap.width, 360 / bitmap.height)
  for (let resize = 0; resize < 4; resize += 1) {
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(bitmap.width * scale))
    canvas.height = Math.max(1, Math.round(bitmap.height * scale))
    const context = canvas.getContext('2d')
    if (!context) return null
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    for (const quality of [0.82, 0.7, 0.58, 0.46]) {
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality))
      if (blob && blob.size <= 200 * 1024) return blob
    }
    scale *= 0.82
  }
  return null
}

async function blobToBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer())
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, Math.min(offset + 0x8000, bytes.length)))
  }
  return btoa(binary)
}

type RenderedVideo = { url: string; extension: 'mp4' | 'webm'; preset?: MotionExportPreset; revision?: number }

interface Props {
  artifact: VisualArtifactPayload
  theme: ThemePreference
  reducedMotion: boolean
  active?: boolean
  reviewRequest?: MotionReviewRequest
  motionSampleReviewRequest?: MotionSampleReviewRequest
  sessionId?: string | null
}

export function MotionArtifact({ artifact, theme, reducedMotion, active = true, reviewRequest, motionSampleReviewRequest, sessionId }: Props) {
  const [port, setPort] = useState<MessagePort | null>(null)
  const [state, setState] = useState<'playing' | 'paused' | 'ended'>('paused')
  const [currentTimeMs, setCurrentTimeMs] = useState(0)
  const [hasMotionCanvas, setHasMotionCanvas] = useState(false)
  const [hasFrameRenderer, setHasFrameRenderer] = useState(false)
  const [timelineBeats, setTimelineBeats] = useState<MotionTimelineBeat[]>([])
  const [canvasSize, setCanvasSize] = useState({ width: 0, height: 0 })
  const [exportProgress, setExportProgress] = useState(0)
  const [exportPreset, setExportPreset] = useState<MotionExportPreset>('balanced')
  const [exportState, setExportState] = useState<'idle' | 'recording' | 'complete' | 'cancelled' | 'error'>('idle')
  const [exportError, setExportError] = useState<string | null>(null)
  const [renderedVideo, setRenderedVideo] = useState<RenderedVideo | null>(null)
  const exportStateRef = useRef(exportState)
  const portRef = useRef(port)
  const duration = artifact.durationMs ?? 1
  const chunks = useRef<Uint8Array[]>([])
  const mimeType = useRef<string>('')
  const framePending = useRef<PendingFrame | null>(null)
  const frameExportCancelled = useRef(false)
  const frameExportRunning = useRef(false)
  const frameExportRevision = useRef<number | null>(null)
  const playbackStateRef = useRef<'playing' | 'paused' | 'ended'>('paused')
  const playbackTimeRef = useRef(0)
  const pauseWaiter = useRef<(() => void) | null>(null)
  const renderedVideoUrl = useRef<string | null>(null)
  const previewRequestId = useRef(1_000_000_000)
  const lastReviewRequestId = useRef<number | null>(null)
  const lastSampleReviewRequestId = useRef<string | null>(null)
  const renderId = useRef(`idle-${artifact.artifactId}-${artifact.revision}`)
  const snapshotRef = useRef<MotionRenderSnapshot | null>(null)
  const beatsRef = useRef<MotionTimelineBeat[]>([])
  const requestedAudioStatus: MotionAudioStatus = artifact.soundtrack?.cues.length ? 'pending' : 'not_requested'
  const renderSnapshot = useSyncExternalStore(
    useCallback((notify) => subscribeMotionRender(artifact.artifactId, artifact.revision, () => notify()), [artifact.artifactId, artifact.revision]),
    useCallback(() => getMotionRenderSnapshot(artifact.artifactId, artifact.revision), [artifact.artifactId, artifact.revision]),
    () => null,
  )
  const publishRender = useCallback((patch: Partial<MotionRenderSnapshot>) => {
    const base: MotionRenderSnapshot = snapshotRef.current ?? {
      artifactId: artifact.artifactId,
      revision: artifact.revision,
      renderId: renderId.current,
      status: 'idle',
      completedFrames: 0,
      totalFrames: null,
      fps: null,
      lastCompletedIndex: null,
      currentTimeMs: 0,
      currentFrameUrl: null,
      beats: beatsRef.current,
      samples: [],
      audioStatus: requestedAudioStatus,
    }
    const next: MotionRenderSnapshot = {
      ...base,
      ...patch,
      artifactId: artifact.artifactId,
      revision: artifact.revision,
      renderId: renderId.current,
      beats: patch.beats ?? beatsRef.current,
    }
    if (publishMotionRenderSnapshot(next)) {
      snapshotRef.current = getMotionRenderSnapshot(artifact.artifactId, artifact.revision)
      return true
    }
    return false
  }, [artifact.artifactId, artifact.revision, requestedAudioStatus])
  const onPlayback = useCallback((message: { state: 'playing' | 'paused' | 'ended'; currentTimeMs: number }) => {
    playbackStateRef.current = message.state
    playbackTimeRef.current = Math.min(duration, message.currentTimeMs)
    if (message.state !== 'playing') {
      pauseWaiter.current?.()
      pauseWaiter.current = null
    }
    setState(message.state)
    setCurrentTimeMs(Math.min(duration, message.currentTimeMs))
  }, [duration])
  const exportMime = useMemo(() => {
    return getSupportedExportMimeType(typeof MediaRecorder === 'undefined' ? undefined : MediaRecorder)
  }, [])
  const frameExportAvailable = useMemo(canRenderMotionFrames, [])
  const useFrameExport = hasFrameRenderer && frameExportAvailable
  const canExport = useFrameExport || Boolean(exportMime)
  const onReady = useCallback((message: Extract<VisualArtifactBridgeMessage, { type: 'ready' }>) => {
    setHasMotionCanvas(message.motionCanvas)
    setHasFrameRenderer(message.frameRenderer === true)
    if (message.canvasWidth && message.canvasHeight) {
      setCanvasSize({ width: message.canvasWidth, height: message.canvasHeight })
    }
  }, [])
  const onTimeline = useCallback((message: Extract<VisualArtifactBridgeMessage, { type: 'timeline' }>) => {
    beatsRef.current = message.beats
    setTimelineBeats(message.beats)
    publishRender({ beats: message.beats })
  }, [publishRender])
  const onFrame = useCallback((message: Extract<VisualArtifactBridgeMessage, { type: 'rendered_frame' | 'frame_error' }>) => {
    const pending = framePending.current
    if (!pending || pending.requestId !== message.requestId) {
      if (message.type === 'rendered_frame') message.bitmap.close()
      return
    }
    window.clearTimeout(pending.timeoutId)
    framePending.current = null
    if (message.type === 'frame_error') pending.reject(new Error(message.message))
    else pending.resolve({ requestId: message.requestId, bitmap: message.bitmap })
  }, [])
  const requestFrameAt = useCallback((currentTime: number, requestId: number) => new Promise<{ requestId: number; bitmap: ImageBitmap }>((resolve, reject) => {
    if (!port) {
      reject(new Error('The motion renderer is unavailable.'))
      return
    }
    const timeoutId = window.setTimeout(() => {
      if (framePending.current?.requestId === requestId) framePending.current = null
      reject(new Error('The motion renderer did not return a frame in time.'))
    }, 30_000)
    framePending.current = { requestId, resolve, reject, timeoutId }
    port.postMessage({
      type: 'command',
      command: { type: 'render_frame', requestId, currentTimeMs: currentTime },
    })
  }), [port])

  useEffect(() => {
    beatsRef.current = []
    setTimelineBeats([])
    renderId.current = `idle-${artifact.artifactId}-${artifact.revision}`
    snapshotRef.current = null
    publishRender({
      status: 'idle', completedFrames: 0, totalFrames: null, fps: null,
      lastCompletedIndex: null, currentTimeMs: 0, currentFrameUrl: null,
      samples: [], audioStatus: requestedAudioStatus, beats: [],
    })
  }, [artifact.artifactId, artifact.revision, publishRender, requestedAudioStatus])
  const clearRenderedVideo = useCallback(() => {
    if (renderedVideoUrl.current) URL.revokeObjectURL(renderedVideoUrl.current)
    renderedVideoUrl.current = null
    setRenderedVideo(null)
  }, [])
  const presentVideo = useCallback((blob: Blob, extension: 'mp4' | 'webm', preset?: MotionExportPreset, revision?: number) => {
    if (renderedVideoUrl.current) URL.revokeObjectURL(renderedVideoUrl.current)
    const url = URL.createObjectURL(blob)
    renderedVideoUrl.current = url
    setRenderedVideo({ url, extension, preset, revision })
  }, [])
  useEffect(() => {
    if (renderedVideo && renderedVideo.revision !== artifact.revision) clearRenderedVideo()
  }, [artifact.revision, clearRenderedVideo, renderedVideo])
  const inspectFrame = useCallback(async (frameIndex: number) => {
    if (!port || !hasFrameRenderer || frameExportRunning.current) return
    const totalFrames = Math.ceil((duration / 1000) * MOTION_FPS)
    const boundedFrame = Math.max(0, Math.min(totalFrames - 1, Math.floor(frameIndex)))
    const timeMs = Math.min(duration, (boundedFrame / MOTION_FPS) * 1000)
    const requestId = previewRequestId.current++
    setCurrentTimeMs(timeMs)
    playbackTimeRef.current = timeMs
    publishRender({ currentTimeMs: timeMs, currentFrameUrl: null })
    try {
      const frame = await requestFrameAt(timeMs, requestId)
      let objectUrl: string | null = null
      try {
        objectUrl = await bitmapToPreviewUrl(frame.bitmap)
      } finally {
        frame.bitmap.close()
      }
      if (!objectUrl) return
      if (!publishRender({ currentFrameUrl: objectUrl, currentTimeMs: timeMs })) URL.revokeObjectURL(objectUrl)
    } catch {
      // The existing playback/renderer surface remains usable if a review seek fails.
    }
  }, [duration, hasFrameRenderer, port, publishRender, requestFrameAt])
  useEffect(() => {
    if (!active || !hasFrameRenderer || !reviewRequest || lastReviewRequestId.current === reviewRequest.id) return
    lastReviewRequestId.current = reviewRequest.id
    void inspectFrame(reviewRequest.frameIndex)
  }, [active, hasFrameRenderer, inspectFrame, reviewRequest])

  useEffect(() => {
    if (!active || !hasFrameRenderer || !port || !sessionId || !motionSampleReviewRequest
      || lastSampleReviewRequestId.current === motionSampleReviewRequest.id) return
    lastSampleReviewRequestId.current = motionSampleReviewRequest.id
    void (async () => {
      const previews: MotionReviewSample[] = []
      const uploads: Array<{ sampleId: string; frameIndex: number; timestampMs: number; mimeType: 'image/jpeg'; imageBase64: string }> = []
      let previewsPublished = false
      try {
        for (const sample of motionSampleReviewRequest.samples.slice(0, MAX_REVIEW_SAMPLES)) {
          const frame = await requestFrameAt(sample.timestampMs, previewRequestId.current++)
          let blob: Blob | null = null
          try {
            blob = await bitmapToReviewBlob(frame.bitmap)
          } finally {
            frame.bitmap.close()
          }
          if (!blob) throw new Error(`Could not encode review sample ${sample.sampleId}.`)
          const imageBase64 = await blobToBase64(blob)
          uploads.push({ sampleId: sample.sampleId, frameIndex: sample.frameIndex, timestampMs: sample.timestampMs, mimeType: 'image/jpeg', imageBase64 })
          previews.push({ ...sample, objectUrl: URL.createObjectURL(blob) })
        }
        if (!previews.length) return
        if (!publishRender({ samples: previews })) {
          previews.forEach((sample) => URL.revokeObjectURL(sample.objectUrl))
          return
        }
        previewsPublished = true
        await postMotionReviewSamples(sessionId, motionSampleReviewRequest.jobId, {
          sampleRequestId: motionSampleReviewRequest.sampleRequestId,
          artifactId: artifact.artifactId,
          artifactRevision: artifact.revision,
          samples: uploads,
        })
      } catch {
        if (!previewsPublished) previews.forEach((sample) => URL.revokeObjectURL(sample.objectUrl))
        // The agent's rendezvous expires with an explicit unavailable result.
      }
    })()
  }, [active, artifact.artifactId, artifact.revision, hasFrameRenderer, motionSampleReviewRequest, port, publishRender, requestFrameAt, sessionId])

  useEffect(() => {
    if (!port) return
    const onMessage = (event: MessageEvent) => {
      const data = event.data as { type?: string; bytes?: Uint8Array; mimeType?: string; final?: boolean; state?: string; message?: string }
      if (data?.type === 'export_status') {
        if (data.state === 'recording') {
          setExportState('recording')
          setExportError(null)
        } else if (data.state === 'error') {
          chunks.current = []
          setExportState('error')
          setExportError(data.message ?? 'The video export failed.')
          if (!frameExportRunning.current) publishRender({ status: 'failed', audioStatus: requestedAudioStatus === 'pending' ? 'unavailable' : requestedAudioStatus })
        } else if (data.state === 'cancelled') {
          chunks.current = []
          setExportState('cancelled')
          if (!frameExportRunning.current) publishRender({ status: 'cancelled', audioStatus: requestedAudioStatus === 'pending' ? 'unavailable' : requestedAudioStatus })
        } else if (data.state === 'complete') {
          setExportState('complete')
          if (!frameExportRunning.current) publishRender({ status: 'complete', audioStatus: requestedAudioStatus === 'pending' ? 'unavailable' : requestedAudioStatus })
        }
        return
      }
      if (data?.type !== 'export_chunk' || !(data.bytes instanceof Uint8Array)) return
      chunks.current.push(data.bytes)
      mimeType.current = data.mimeType ?? exportMime ?? 'video/webm'
      if (data.final) {
        const blobParts = chunks.current.map((chunk) => chunk.buffer.slice(
          chunk.byteOffset,
          chunk.byteOffset + chunk.byteLength,
        ) as ArrayBuffer)
        const blob = new Blob(blobParts, { type: mimeType.current })
        chunks.current = []
        presentVideo(blob, mimeType.current.includes('mp4') ? 'mp4' : 'webm', undefined, artifact.revision)
      }
    }
    port.addEventListener('message', onMessage)
    return () => port.removeEventListener('message', onMessage)
  }, [artifact.artifactId, artifact.revision, exportMime, port, presentVideo, publishRender, requestedAudioStatus])

  useEffect(() => () => {
    if (exportStateRef.current === 'recording') portRef.current?.postMessage({ type: 'export_cancel' })
    frameExportCancelled.current = true
    if (snapshotRef.current?.status === 'rendering') publishRender({ status: 'cancelled', audioStatus: requestedAudioStatus === 'pending' ? 'unavailable' : requestedAudioStatus })
    pauseWaiter.current?.()
    pauseWaiter.current = null
    if (framePending.current) {
      window.clearTimeout(framePending.current.timeoutId)
      framePending.current.reject(new DOMException('Video export cancelled.', 'AbortError'))
      framePending.current = null
    }
  }, [publishRender, requestedAudioStatus])

  useEffect(() => () => {
    if (renderedVideoUrl.current) URL.revokeObjectURL(renderedVideoUrl.current)
    renderedVideoUrl.current = null
  }, [])

  useEffect(() => {
    exportStateRef.current = exportState
    portRef.current = port
  }, [exportState, port])

  const command = (name: string, value?: number) => port?.postMessage({ type: 'command', command: value === undefined ? name : { type: name, currentTimeMs: value } })
  useEffect(() => {
    if (!active && state === 'playing') {
      port?.postMessage({ type: 'command', command: 'pause' })
    }
  }, [active, state, port])
  useEffect(() => {
    if (!active && exportState === 'recording') {
      if (frameExportRunning.current) {
        frameExportCancelled.current = true
        pauseWaiter.current?.()
        pauseWaiter.current = null
        if (framePending.current) {
          window.clearTimeout(framePending.current.timeoutId)
          framePending.current.reject(new DOMException('Video export cancelled.', 'AbortError'))
          framePending.current = null
        }
      } else {
        port?.postMessage({ type: 'export_cancel' })
      }
    }
  }, [active, exportState, port])
  useEffect(() => {
    if (frameExportRevision.current === artifact.revision) return
    if (frameExportRunning.current) {
      frameExportCancelled.current = true
      pauseWaiter.current?.()
      pauseWaiter.current = null
      if (framePending.current) {
        window.clearTimeout(framePending.current.timeoutId)
        framePending.current.reject(new DOMException('The motion artifact changed during export.', 'AbortError'))
        framePending.current = null
      }
    } else if (exportStateRef.current === 'recording') {
      chunks.current = []
      portRef.current?.postMessage({ type: 'export_cancel' })
      setExportState('cancelled')
    }
  }, [artifact.revision])
  const downloadVideo = () => {
    if (!renderedVideo) return
    const anchor = document.createElement('a')
    anchor.href = renderedVideo.url
    anchor.download = `${artifact.artifactId}${renderedVideo.revision === undefined ? '' : `-r${renderedVideo.revision}`}${renderedVideo.preset ? `-${renderedVideo.preset}` : ''}.${renderedVideo.extension}`
    anchor.click()
  }
  const beginRender = (totalFrames: number | null) => {
    motionRenderSequence += 1
    renderId.current = `${artifact.artifactId}-r${artifact.revision}-render-${motionRenderSequence}`
    snapshotRef.current = null
    publishRender({
      status: 'rendering', completedFrames: 0, totalFrames,
      fps: totalFrames === null ? null : MOTION_FPS,
      lastCompletedIndex: null, currentTimeMs: 0, currentFrameUrl: null,
      beats: beatsRef.current, samples: [], audioStatus: requestedAudioStatus,
    })
  }
  const exportFrames = async () => {
    if (!port || !hasFrameRenderer || !canvasSize.width || !canvasSize.height || !frameExportAvailable) return
    frameExportCancelled.current = false
    frameExportRunning.current = true
    const pinnedRevision = artifact.revision
    const pinnedPreset = exportPreset
    frameExportRevision.current = pinnedRevision
    setExportProgress(0)
    const resumePreview = playbackStateRef.current === 'playing'
    const restoreTimeMs = playbackTimeRef.current
    try {
      if (resumePreview) {
        await new Promise<void>((resolve, reject) => {
          const timeoutId = window.setTimeout(() => {
            pauseWaiter.current = null
            reject(new Error('Pause the preview before rendering so its frames stay consistent.'))
          }, 5_000)
          pauseWaiter.current = () => {
            window.clearTimeout(timeoutId)
            resolve()
          }
          port.postMessage({ type: 'command', command: 'pause' })
        })
      }
      const { exportMotionFrames } = await import('@/lib/motion-video-export')
      const totalFrames = Math.ceil((duration / 1000) * MOTION_FPS)
      const samplePlan = representativeFrames(beatsRef.current, totalFrames)
      const sampleByFrame = new Map(samplePlan.map((sample) => [sample.frameIndex, sample]))
      const result = await exportMotionFrames({
        durationMs: duration,
        canvasWidth: canvasSize.width,
        canvasHeight: canvasSize.height,
        preset: pinnedPreset,
        soundtrack: artifact.soundtrack,
        onAudioStatus: (audioStatus) => publishRender({ audioStatus }),
        isCancelled: () => frameExportCancelled.current,
        onProgress: (framesRendered, frameTotal) => {
          setExportProgress(framesRendered)
          publishRender({
            status: 'rendering', completedFrames: framesRendered, totalFrames: frameTotal,
            fps: MOTION_FPS, lastCompletedIndex: framesRendered - 1,
            currentTimeMs: Math.min(duration, ((framesRendered - 1) / MOTION_FPS) * 1000),
          })
        },
        onRenderedFrame: async ({ frameIndex, currentTimeMs, bitmap }) => {
          const descriptor = sampleByFrame.get(frameIndex)
          if (!descriptor) return
          let objectUrl: string | null
          try {
            objectUrl = await bitmapToPreviewUrl(bitmap)
          } catch {
            return
          }
          if (!objectUrl) return
          if (frameExportCancelled.current || artifact.revision !== pinnedRevision) {
            URL.revokeObjectURL(objectUrl)
            return
          }
          const sample: MotionReviewSample = {
            sampleId: `${artifact.artifactId}-r${pinnedRevision}-f${frameIndex}`,
            beatId: descriptor.beatId,
            frameIndex,
            timestampMs: currentTimeMs,
            role: descriptor.role,
            objectUrl,
          }
          const samples = [
            ...(snapshotRef.current?.samples ?? []).filter((item) => item.sampleId !== sample.sampleId),
            sample,
          ].slice(-MAX_REVIEW_SAMPLES)
          if (!publishRender({ samples, currentTimeMs })) URL.revokeObjectURL(objectUrl)
        },
        requestFrame: requestFrameAt,
      })
      if (frameExportCancelled.current || frameExportRevision.current !== pinnedRevision) {
        throw new DOMException('Video export cancelled.', 'AbortError')
      }
      presentVideo(result.blob, result.extension, pinnedPreset, pinnedRevision)
      setExportState('complete')
      setExportError(null)
      publishRender({
        status: 'complete', completedFrames: result.frameCount, totalFrames: result.frameCount,
        fps: MOTION_FPS, lastCompletedIndex: result.frameCount - 1, currentTimeMs: duration,
        audioStatus: result.audioStatus,
      })
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        setExportState('cancelled')
        publishRender({ status: 'cancelled', audioStatus: requestedAudioStatus === 'pending' ? 'unavailable' : requestedAudioStatus })
      }
      else {
        setExportState('error')
        setExportError(error instanceof Error ? error.message : 'The frame-based video export failed.')
        publishRender({ status: 'failed', audioStatus: requestedAudioStatus === 'pending' ? 'unavailable' : requestedAudioStatus })
      }
    } finally {
      if (active) {
        port.postMessage({ type: 'command', command: { type: 'seek', currentTimeMs: restoreTimeMs } })
        if (resumePreview) port.postMessage({ type: 'command', command: 'play' })
      }
      frameExportRunning.current = false
      frameExportRevision.current = null
    }
  }
  const exportVideo = () => {
    if (!port || !hasMotionCanvas || !active || exportState === 'recording' || !canExport) return
    beginRender(useFrameExport ? Math.ceil((duration / 1000) * MOTION_FPS) : null)
    if (useFrameExport) {
      setExportState('recording')
      setExportError(null)
      void exportFrames()
      return
    }
    if (!exportMime) return
    chunks.current = []
    setExportState('recording')
    setExportError(null)
    if (requestedAudioStatus === 'pending') publishRender({ audioStatus: 'unavailable' })
    port.postMessage({ type: 'export_request', mimeType: exportMime, durationMs: duration })
  }
  const cancelExport = () => {
    if (frameExportRunning.current) {
      frameExportCancelled.current = true
      pauseWaiter.current?.()
      pauseWaiter.current = null
      if (framePending.current) {
        window.clearTimeout(framePending.current.timeoutId)
        framePending.current.reject(new DOMException('Video export cancelled.', 'AbortError'))
        framePending.current = null
      }
      return
    }
    port?.postMessage({ type: 'export_cancel' })
  }
  const totalTimelineFrames = Math.ceil((duration / 1000) * MOTION_FPS)
  const currentFrameIndex = Math.min(totalTimelineFrames - 1, Math.round((currentTimeMs / 1000) * MOTION_FPS))
  const goToFrame = (frameIndex: number) => {
    const boundedFrame = Math.max(0, Math.min(totalTimelineFrames - 1, frameIndex))
    const timeMs = Math.min(duration, (boundedFrame / MOTION_FPS) * 1000)
    setCurrentTimeMs(timeMs)
    playbackTimeRef.current = timeMs
    command('seek', timeMs)
    void inspectFrame(boundedFrame)
  }

  return (
    <section className="my-2 overflow-hidden rounded-xl border border-(--color-border) bg-(--color-surface)" aria-label={`${artifact.title} motion explainer`}>
      <header className="px-4 py-3"><h3 className="text-sm font-semibold">{artifact.title}</h3><p className="mt-1 text-xs text-(--color-text-subtle)">{artifact.summary}</p></header>
      <VisualArtifactFrame artifact={artifact} theme={theme} reducedMotion={reducedMotion} onPort={setPort} onPlayback={onPlayback} onTimeline={onTimeline} onReady={onReady} onFrame={onFrame} />
      <div className="space-y-2 border-t border-(--color-border) p-3">
        <div className="flex flex-wrap items-center gap-2">
          {useFrameExport && (
            <label className="flex items-center gap-2 text-xs text-(--color-text-subtle)">
              <span>Video quality</span>
              <SelectControl
                ariaLabel="Video quality"
                value={exportPreset}
                onValueChange={(value) => setExportPreset(value as MotionExportPreset)}
                disabled={exportState === 'recording'}
                size="sm"
                className="min-w-40 bg-(--bg-key) text-xs"
                options={[
                  { value: 'balanced', label: '720p · Balanced' },
                  { value: 'high', label: '1080p · High' },
                ]}
              />
            </label>
          )}
          <button type="button" onClick={() => command('play')} disabled={state === 'playing' || exportState === 'recording'}>Play</button>
          <button type="button" onClick={() => command('pause')} disabled={state !== 'playing' || exportState === 'recording'}>Pause</button>
          <button type="button" onClick={() => { command('restart'); setCurrentTimeMs(0) }} disabled={exportState === 'recording'}>Restart</button>
          <button type="button" onClick={exportVideo} disabled={!canExport || !port || !hasMotionCanvas || !active || exportState === 'recording'}>{exportState === 'recording' ? (useFrameExport ? `Rendering ${exportProgress}%…` : 'Exporting…') : useFrameExport ? 'Render video' : `Export ${exportMime?.includes('mp4') ? 'MP4' : 'WebM'}`}</button>
          {exportState === 'recording' && <button type="button" onClick={cancelExport}>Cancel export</button>}
          {!canExport && <span className="text-xs text-(--color-text-subtle)">Video export is unavailable in this browser.</span>}
          {canExport && !hasMotionCanvas && <span className="text-xs text-(--color-text-subtle)">Export is unavailable because this explainer has no marked canvas.</span>}
          {useFrameExport && exportState !== 'recording' && <span className="text-xs text-(--color-text-subtle)">Renders one exact canvas frame at a time and encodes the finished video locally.</span>}
          {exportState === 'recording' && <span role="status" className="text-xs text-(--color-text-subtle)">{renderSnapshot?.audioStatus === 'rendering' ? 'Preparing soundtrack separately from video frame progress. ' : ''}{useFrameExport ? `Rendering deterministic frame ${exportProgress} / ${totalTimelineFrames}. Keep this Workbench view open until the file is ready.` : 'Recording video; frame count is unavailable. Keep this Workbench view open until export finishes.'}</span>}
          {exportState === 'complete' && <span role="status" className="text-xs text-(--color-text-subtle)">{renderSnapshot?.audioStatus === 'included' ? 'Video and soundtrack are ready to preview in Workbench.' : renderSnapshot?.audioStatus === 'unavailable' ? 'Video is ready; sound was not rendered.' : 'Video is ready; no soundtrack was requested.'}</span>}
          {exportState === 'cancelled' && <span role="status" className="text-xs text-(--color-text-subtle)">Video export cancelled.</span>}
          {exportError && <span role="alert" className="text-xs text-(--color-danger)">{exportError}</span>}
        </div>
        <label className="flex items-center gap-3 text-xs text-(--color-text-subtle)">
          <span className="sr-only">Motion timeline</span>
          <span>{(currentTimeMs / 1000).toFixed(1)}s</span>
          <input aria-label="Motion timeline" type="range" min={0} max={duration} value={currentTimeMs} onChange={(event) => { const next = Number(event.currentTarget.value); setCurrentTimeMs(next); command('seek', next) }} onPointerUp={() => goToFrame(currentFrameIndex)} onKeyUp={() => goToFrame(currentFrameIndex)} disabled={exportState === 'recording'} className="min-w-0 flex-1" />
          <span>{(duration / 1000).toFixed(1)}s</span>
        </label>
        {hasFrameRenderer && (
          <section className="space-y-2 rounded-lg border border-(--color-border-subtle) bg-(--bg-card) p-2" aria-label="Motion frame review">
            <div className="flex items-center justify-between gap-2">
              <button type="button" onClick={() => goToFrame(currentFrameIndex - 1)} disabled={currentFrameIndex <= 0 || exportState === 'recording'} className="rounded-md border border-(--color-border) px-2 py-1 text-xs disabled:opacity-50">Previous frame</button>
              <p role="status" className="text-xs text-(--color-text-subtle)">Frame {currentFrameIndex + 1} / {totalTimelineFrames} · {(currentTimeMs / 1000).toFixed(3)}s</p>
              <button type="button" onClick={() => goToFrame(currentFrameIndex + 1)} disabled={currentFrameIndex >= totalTimelineFrames - 1 || exportState === 'recording'} className="rounded-md border border-(--color-border) px-2 py-1 text-xs disabled:opacity-50">Next frame</button>
            </div>
            {renderSnapshot?.currentFrameUrl && (
              <img src={renderSnapshot.currentFrameUrl} alt={`Motion frame ${currentFrameIndex + 1} at ${(currentTimeMs / 1000).toFixed(3)} seconds`} className="mx-auto aspect-video max-h-48 rounded-md object-contain" />
            )}
            {timelineBeats.length > 0 && (
              <div className="flex gap-2 overflow-x-auto" aria-label="Motion story beats">
                {timelineBeats.map((beat) => (
                  <button key={beat.id} type="button" onClick={() => goToFrame(beat.startFrame)} className="shrink-0 rounded-md border border-(--color-border) px-2 py-1 text-left text-xs hover:bg-(--bg-key)">
                    <span className="block font-medium">{beat.title}</span>
                    <span className="text-(--color-text-subtle)">Frames {beat.startFrame + 1}–{beat.endFrame + 1}</span>
                    {beat.markers.map((marker, index) => <span key={`${marker.frame}-${index}`} className="ml-1 text-(--color-accent)">{marker.kind} · {marker.frame + 1}</span>)}
                  </button>
                ))}
              </div>
            )}
            {renderSnapshot && renderSnapshot.samples.length > 0 && (
              <div className="flex gap-2 overflow-x-auto" aria-label="Selected frame previews">
                {renderSnapshot.samples.map((sample) => {
                  const beatTitle = renderSnapshot.beats.find((beat) => beat.id === sample.beatId)?.title ?? 'Preview'
                  return (
                    <button key={sample.sampleId} type="button" onClick={() => goToFrame(sample.frameIndex)} className="w-32 shrink-0 overflow-hidden rounded-md border border-(--color-border) text-left">
                      <img src={sample.objectUrl} alt={`${beatTitle}, frame ${sample.frameIndex + 1}`} className="aspect-video w-full object-cover" />
                      <span className="block truncate px-1 py-1 text-[10px]">{beatTitle} · frame {sample.frameIndex + 1} · {(sample.timestampMs / 1000).toFixed(2)}s</span>
                    </button>
                  )
                })}
              </div>
            )}
          </section>
        )}
        {renderedVideo && (
          <div className="space-y-2 rounded-lg border border-(--color-border-subtle) bg-(--bg-card) p-2">
            <video src={renderedVideo.url} controls preload="metadata" className="max-h-[480px] w-full rounded-md bg-black" aria-label={`${artifact.title} rendered video`} />
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-(--color-text-subtle)">{renderedVideo.preset === 'high' ? '1080p · High' : renderedVideo.preset === 'balanced' ? '720p · Balanced' : renderedVideo.extension.toUpperCase()} preview ready{renderedVideo.revision === undefined ? '' : ` · revision ${renderedVideo.revision}`}</span>
              <button type="button" onClick={downloadVideo} className="rounded-md border border-(--color-border) px-3 py-1.5 text-xs font-medium hover:bg-(--bg-key)">Download video</button>
            </div>
          </div>
        )}
        {reducedMotion && <p className="text-xs text-(--color-text-subtle)">Reduced motion is on. Playback starts only when you choose Play.</p>}
      </div>
    </section>
  )
}
