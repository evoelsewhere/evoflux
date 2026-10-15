import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { VisualArtifactPayload } from '@/api/types'
import type { ThemePreference } from '@/lib/theme'
import { VisualArtifactFrame } from '@/components/VisualArtifactFrame'
import { getSupportedExportMimeType } from '@/lib/visual-artifact-export'

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
  const [exportState, setExportState] = useState<'idle' | 'recording' | 'complete' | 'cancelled' | 'error'>('idle')
  const [exportError, setExportError] = useState<string | null>(null)
  const exportStateRef = useRef(exportState)
  const portRef = useRef(port)
  const duration = artifact.durationMs ?? 1
  const chunks = useRef<Uint8Array[]>([])
  const mimeType = useRef<string>('')
  const onPlayback = useCallback((message: { state: 'playing' | 'paused' | 'ended'; currentTimeMs: number }) => {
    setState(message.state)
    setCurrentTimeMs(Math.min(duration, message.currentTimeMs))
  }, [duration])
  const exportMime = useMemo(() => {
    return getSupportedExportMimeType(typeof MediaRecorder === 'undefined' ? undefined : MediaRecorder)
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
        const url = URL.createObjectURL(blob)
        const anchor = document.createElement('a')
        anchor.href = url
        anchor.download = `${artifact.artifactId}.${mimeType.current.includes('mp4') ? 'mp4' : 'webm'}`
        anchor.click()
        window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      }
    }
    port.addEventListener('message', onMessage)
    return () => port.removeEventListener('message', onMessage)
  }, [artifact.artifactId, exportMime, port])

  useEffect(() => () => {
    if (exportStateRef.current === 'recording') portRef.current?.postMessage({ type: 'export_cancel' })
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
    if (!active && exportState === 'recording') port?.postMessage({ type: 'export_cancel' })
  }, [active, exportState, port])
  const exportVideo = () => {
    if (!exportMime || !port || !hasMotionCanvas || !active || exportState === 'recording') return
    chunks.current = []
    setExportState('recording')
    setExportError(null)
    port.postMessage({ type: 'export_request', mimeType: exportMime, durationMs: duration })
  }
  const cancelExport = () => port?.postMessage({ type: 'export_cancel' })

  return (
    <section className="my-2 overflow-hidden rounded-xl border border-(--color-border) bg-(--color-surface)" aria-label={`${artifact.title} motion explainer`}>
      <header className="px-4 py-3"><h3 className="text-sm font-semibold">{artifact.title}</h3><p className="mt-1 text-xs text-(--color-text-subtle)">{artifact.summary}</p></header>
      <VisualArtifactFrame artifact={artifact} theme={theme} reducedMotion={reducedMotion} onPort={setPort} onPlayback={onPlayback} onReady={(message) => setHasMotionCanvas(message.motionCanvas)} />
      <div className="space-y-2 border-t border-(--color-border) p-3">
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => command('play')} disabled={state === 'playing'}>Play</button>
          <button type="button" onClick={() => command('pause')} disabled={state !== 'playing'}>Pause</button>
          <button type="button" onClick={() => { command('restart'); setCurrentTimeMs(0) }}>Restart</button>
          <button type="button" onClick={exportVideo} disabled={!exportMime || !port || !hasMotionCanvas || !active || exportState === 'recording'}>{exportState === 'recording' ? 'Exporting…' : `Export ${exportMime?.includes('mp4') ? 'MP4' : 'WebM'}`}</button>
          {exportState === 'recording' && <button type="button" onClick={cancelExport}>Cancel export</button>}
          {!exportMime && <span className="text-xs text-(--color-text-subtle)">Video export is unavailable in this browser.</span>}
          {exportMime && !hasMotionCanvas && <span className="text-xs text-(--color-text-subtle)">Export is unavailable because this explainer has no marked canvas.</span>}
          {exportState === 'recording' && <span role="status" className="text-xs text-(--color-text-subtle)">Recording from the start. Keep this Workbench view open until export finishes.</span>}
          {exportState === 'complete' && <span role="status" className="text-xs text-(--color-text-subtle)">Video downloaded.</span>}
          {exportState === 'cancelled' && <span role="status" className="text-xs text-(--color-text-subtle)">Video export cancelled.</span>}
          {exportError && <span role="alert" className="text-xs text-(--color-danger)">{exportError}</span>}
        </div>
        <label className="flex items-center gap-3 text-xs text-(--color-text-subtle)">
          <span className="sr-only">Motion timeline</span>
          <span>{(currentTimeMs / 1000).toFixed(1)}s</span>
          <input aria-label="Motion timeline" type="range" min={0} max={duration} value={currentTimeMs} onChange={(event) => { const next = Number(event.currentTarget.value); setCurrentTimeMs(next); command('seek', next) }} className="min-w-0 flex-1" />
          <span>{(duration / 1000).toFixed(1)}s</span>
        </label>
        {reducedMotion && <p className="text-xs text-(--color-text-subtle)">Reduced motion is on. Playback starts only when you choose Play.</p>}
      </div>
    </section>
  )
}
