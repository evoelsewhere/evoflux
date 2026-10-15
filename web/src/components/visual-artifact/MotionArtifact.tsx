import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { VisualArtifactPayload } from '@/api/types'
import type { ThemePreference } from '@/lib/theme'
import { VisualArtifactFrame } from '@/components/VisualArtifactFrame'
import { SelectControl } from '@/components/ui/select'
import { canRenderMotionFrames, getSupportedExportMimeType } from '@/lib/visual-artifact-export'
import type { VisualArtifactBridgeMessage } from '@/lib/visual-artifact-bridge'
import type { MotionExportPreset } from '@/lib/motion-video-export'

type PendingFrame = {
  requestId: number
  resolve: (frame: { requestId: number; bitmap: ImageBitmap }) => void
  reject: (error: Error) => void
  timeoutId: number
}

type RenderedVideo = { url: string; extension: 'mp4' | 'webm'; preset?: MotionExportPreset; revision?: number }

interface Props {
  artifact: VisualArtifactPayload
  theme: ThemePreference
  reducedMotion: boolean
  active?: boolean
}

export function MotionArtifact({ artifact, theme, reducedMotion, active = true }: Props) {
  const [port, setPort] = useState<MessagePort | null>(null)
  const [state, setState] = useState<'playing' | 'paused' | 'ended'>('paused')
  const [currentTimeMs, setCurrentTimeMs] = useState(0)
  const [hasMotionCanvas, setHasMotionCanvas] = useState(false)
  const [hasFrameRenderer, setHasFrameRenderer] = useState(false)
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
        } else if (data.state === 'cancelled') {
          chunks.current = []
          setExportState('cancelled')
        } else if (data.state === 'complete') {
          setExportState('complete')
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
        presentVideo(blob, mimeType.current.includes('mp4') ? 'mp4' : 'webm')
      }
    }
    port.addEventListener('message', onMessage)
    return () => port.removeEventListener('message', onMessage)
  }, [artifact.artifactId, exportMime, port, presentVideo])

  useEffect(() => () => {
    if (exportStateRef.current === 'recording') portRef.current?.postMessage({ type: 'export_cancel' })
    frameExportCancelled.current = true
    pauseWaiter.current?.()
    pauseWaiter.current = null
    if (framePending.current) {
      window.clearTimeout(framePending.current.timeoutId)
      framePending.current.reject(new DOMException('Video export cancelled.', 'AbortError'))
      framePending.current = null
    }
  }, [])

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
    if (!frameExportRunning.current || frameExportRevision.current === artifact.revision) return
    frameExportCancelled.current = true
    pauseWaiter.current?.()
    pauseWaiter.current = null
    if (framePending.current) {
      window.clearTimeout(framePending.current.timeoutId)
      framePending.current.reject(new DOMException('The motion artifact changed during export.', 'AbortError'))
      framePending.current = null
    }
  }, [artifact.revision])
  const downloadVideo = () => {
    if (!renderedVideo) return
    const anchor = document.createElement('a')
    anchor.href = renderedVideo.url
    anchor.download = `${artifact.artifactId}${renderedVideo.revision === undefined ? '' : `-r${renderedVideo.revision}`}${renderedVideo.preset ? `-${renderedVideo.preset}` : ''}.${renderedVideo.extension}`
    anchor.click()
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
      const result = await exportMotionFrames({
        durationMs: duration,
        canvasWidth: canvasSize.width,
        canvasHeight: canvasSize.height,
        preset: pinnedPreset,
        isCancelled: () => frameExportCancelled.current,
        onProgress: (framesRendered, totalFrames) => setExportProgress(Math.floor((framesRendered / totalFrames) * 100)),
        requestFrame: (currentTimeMs, requestId) => new Promise((resolve, reject) => {
          const timeoutId = window.setTimeout(() => {
            if (framePending.current?.requestId === requestId) framePending.current = null
            reject(new Error('The motion renderer did not return a frame in time.'))
          }, 30_000)
          framePending.current = { requestId, resolve, reject, timeoutId }
          port.postMessage({
            type: 'command',
            command: { type: 'render_frame', requestId, currentTimeMs },
          })
        }),
      })
      presentVideo(result.blob, result.extension, pinnedPreset, pinnedRevision)
      setExportState('complete')
      setExportError(null)
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') setExportState('cancelled')
      else {
        setExportState('error')
        setExportError(error instanceof Error ? error.message : 'The frame-based video export failed.')
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
    if (useFrameExport) {
      clearRenderedVideo()
      setExportState('recording')
      setExportError(null)
      void exportFrames()
      return
    }
    if (!exportMime) return
    clearRenderedVideo()
    chunks.current = []
    setExportState('recording')
    setExportError(null)
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

  return (
    <section className="my-2 overflow-hidden rounded-xl border border-(--color-border) bg-(--color-surface)" aria-label={`${artifact.title} motion explainer`}>
      <header className="px-4 py-3"><h3 className="text-sm font-semibold">{artifact.title}</h3><p className="mt-1 text-xs text-(--color-text-subtle)">{artifact.summary}</p></header>
      <VisualArtifactFrame artifact={artifact} theme={theme} reducedMotion={reducedMotion} onPort={setPort} onPlayback={onPlayback} onReady={onReady} onFrame={onFrame} />
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
          {exportState === 'recording' && <span role="status" className="text-xs text-(--color-text-subtle)">{useFrameExport ? `Rendering deterministic frame ${exportProgress}%. Keep this Workbench view open until the file is ready.` : 'Recording from the start. Keep this Workbench view open until export finishes.'}</span>}
          {exportState === 'complete' && <span role="status" className="text-xs text-(--color-text-subtle)">Video is ready to preview in Workbench.</span>}
          {exportState === 'cancelled' && <span role="status" className="text-xs text-(--color-text-subtle)">Video export cancelled.</span>}
          {exportError && <span role="alert" className="text-xs text-(--color-danger)">{exportError}</span>}
        </div>
        <label className="flex items-center gap-3 text-xs text-(--color-text-subtle)">
          <span className="sr-only">Motion timeline</span>
          <span>{(currentTimeMs / 1000).toFixed(1)}s</span>
          <input aria-label="Motion timeline" type="range" min={0} max={duration} value={currentTimeMs} onChange={(event) => { const next = Number(event.currentTarget.value); setCurrentTimeMs(next); command('seek', next) }} disabled={exportState === 'recording'} className="min-w-0 flex-1" />
          <span>{(duration / 1000).toFixed(1)}s</span>
        </label>
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
