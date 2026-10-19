import type { MotionSoundtrackSpec, Scene3DSpec, VisualArtifactKind, VisualArtifactPayload, VisualArtifactSource } from '@/api/types'

export type VisualArtifactBridgeMessage =
  | { type: 'ready'; motionCanvas: boolean; frameRenderer?: boolean; canvasWidth?: number; canvasHeight?: number }
  | { type: 'timeline'; beats: MotionTimelineBeat[] }
  | { type: 'resize'; height: number }
  | { type: 'send_prompt'; prompt: string }
  | { type: 'playback'; currentTimeMs: number; state: 'playing' | 'paused' | 'ended' }
  | { type: 'rendered_frame'; requestId: number; currentTimeMs: number; bitmap: ImageBitmap }
  | { type: 'frame_error'; requestId: number; message: string }
  | { type: 'export_chunk'; mimeType: string; bytes: Uint8Array; final: boolean }
  | { type: 'export_status'; state: 'recording' | 'complete' | 'cancelled' | 'error'; message?: string }

export interface MotionTimelineBeat {
  id: string
  title: string
  startFrame: number
  endFrame: number
  markers: Array<{ frame: number; kind: 'hit' | 'cut' | 'transition' }>
}

const MAX_SOURCE_BYTES = 200_000
const MAX_BRIDGE_CHUNK_BYTES = 64_000
const MAX_MOTION_TIMELINE_BEATS = 64
const MAX_MOTION_BEAT_MARKERS = 32
const MAX_MOTION_FRAME_INDEX = 3_600

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function string(value: unknown, max: number): value is string {
  return typeof value === 'string' && value.length <= max
}

function motionTimeline(value: unknown): MotionTimelineBeat[] | null {
  if (!Array.isArray(value) || value.length < 1 || value.length > MAX_MOTION_TIMELINE_BEATS) return null
  const ids = new Set<string>()
  const beats: MotionTimelineBeat[] = []

  for (const candidate of value) {
    const beat = record(candidate)
    if (
      !beat
      || !string(beat.id, 64)
      || !/^[a-z0-9][a-z0-9_-]{0,63}$/.test(beat.id)
      || ids.has(beat.id)
      || !string(beat.title, 120)
      || !beat.title.trim()
      || !Number.isSafeInteger(beat.startFrame)
      || (beat.startFrame as number) < 0
      || (beat.startFrame as number) > MAX_MOTION_FRAME_INDEX
      || !Number.isSafeInteger(beat.endFrame)
      || (beat.endFrame as number) < (beat.startFrame as number)
      || (beat.endFrame as number) > MAX_MOTION_FRAME_INDEX
      || !Array.isArray(beat.markers)
      || beat.markers.length > MAX_MOTION_BEAT_MARKERS
    ) return null

    const markers: MotionTimelineBeat['markers'] = []
    for (const candidateMarker of beat.markers) {
      const marker = record(candidateMarker)
      if (
        !marker
        || !Number.isSafeInteger(marker.frame)
        || (marker.frame as number) < (beat.startFrame as number)
        || (marker.frame as number) > (beat.endFrame as number)
        || !['hit', 'cut', 'transition'].includes(String(marker.kind))
      ) return null
      markers.push({ frame: marker.frame as number, kind: marker.kind as MotionTimelineBeat['markers'][number]['kind'] })
    }

    ids.add(beat.id)
    beats.push({
      id: beat.id,
      title: beat.title.trim(),
      startFrame: beat.startFrame as number,
      endFrame: beat.endFrame as number,
      markers,
    })
  }

  return beats
}

function scene(value: unknown): Scene3DSpec | null {
  const raw = record(value)
  if (!raw || !Array.isArray(raw.nodes) || raw.nodes.length < 1 || raw.nodes.length > 100) return null
  const ids = new Set<string>()
  const nodes = []
  for (const candidate of raw.nodes) {
    const node = record(candidate)
    if (!node || !string(node.id, 80) || ids.has(node.id)) return null
    if (!['box', 'sphere', 'cylinder', 'torus'].includes(String(node.geometry))) return null
    if (!['accent', 'foreground', 'muted', 'success', 'warning', 'danger', 'info'].includes(String(node.color))) return null
    const vectors = ['position', 'rotation', 'scale'].map((key) => node[key])
    if (!vectors.every((vector) => Array.isArray(vector) && vector.length === 3 && vector.every((n) => typeof n === 'number' && Number.isFinite(n)))) return null
    const [position, rotation, scale] = vectors as number[][]
    if (position.some((n) => n < -100 || n > 100) || rotation.some((n) => n < -6.2832 || n > 6.2832) || scale.some((n) => n < 0.01 || n > 100)) return null
    if (node.label !== undefined && node.label !== null && !string(node.label, 120)) return null
    ids.add(node.id)
    nodes.push(node as unknown as Scene3DSpec['nodes'][number])
  }
  return { nodes }
}

function motionSoundtrack(value: unknown, durationMs: number): MotionSoundtrackSpec | null {
  const raw = record(value)
  if (!raw || !string(raw.style, 80) || !raw.style.trim() || !Array.isArray(raw.cues) || raw.cues.length > 64) return null
  const ids = new Set<string>()
  const cues: MotionSoundtrackSpec['cues'] = []
  for (const candidate of raw.cues) {
    const cue = record(candidate)
    if (
      !cue
      || !string(cue.id, 64)
      || !/^[a-z0-9][a-z0-9_-]{0,63}$/.test(cue.id)
      || ids.has(cue.id)
      || !Number.isSafeInteger(cue.start_ms)
      || (cue.start_ms as number) < 0
      || (cue.start_ms as number) > 120_000
      || !Number.isSafeInteger(cue.duration_ms)
      || (cue.duration_ms as number) < 20
      || (cue.duration_ms as number) > 10_000
      || (cue.start_ms as number) + (cue.duration_ms as number) > durationMs
      || !['sine', 'triangle', 'square', 'sawtooth', 'noise'].includes(String(cue.waveform))
      || typeof cue.frequency_hz !== 'number'
      || !Number.isFinite(cue.frequency_hz)
      || cue.frequency_hz < 30
      || cue.frequency_hz > 12_000
      || typeof cue.gain !== 'number'
      || !Number.isFinite(cue.gain)
      || cue.gain < 0
      || cue.gain > 0.35
    ) return null
    ids.add(cue.id)
    cues.push({
      id: cue.id,
      startMs: cue.start_ms as number,
      durationMs: cue.duration_ms as number,
      waveform: cue.waveform as MotionSoundtrackSpec['cues'][number]['waveform'],
      frequencyHz: cue.frequency_hz,
      gain: cue.gain,
    })
  }
  return { style: raw.style.trim(), cues }
}

export function parseVisualArtifactMessage(raw: unknown, revision = 1): VisualArtifactPayload | null {
  const value = record(raw)
  if (!value || value.type !== 'visual_artifact') return null
  if (!string(value.artifact_id, 80) || !/^[a-z0-9][a-z0-9_-]{0,79}$/.test(value.artifact_id)) return null
  if (!['dashboard', 'motion', 'scene3d'].includes(String(value.kind))) return null
  if (!string(value.title, 120) || !value.title || !string(value.summary, 500)) return null
  const kind = value.kind as VisualArtifactKind
  const sourceHtml = value.source_html
  const sceneSpec = value.scene === null || value.scene === undefined ? null : scene(value.scene)
  if (kind === 'scene3d') {
    if (!sceneSpec || sourceHtml !== null && sourceHtml !== undefined) return null
  } else {
    if (!string(sourceHtml, MAX_SOURCE_BYTES) || new TextEncoder().encode(sourceHtml).byteLength > MAX_SOURCE_BYTES || sceneSpec) return null
  }
  if (kind === 'motion' && (!Number.isInteger(value.duration_ms) || (value.duration_ms as number) < 1 || (value.duration_ms as number) > 120_000)) return null
  if (kind !== 'motion' && value.duration_ms !== null && value.duration_ms !== undefined) return null
  if (kind !== 'motion' && value.soundtrack !== null && value.soundtrack !== undefined) return null
  const durationMs = typeof value.duration_ms === 'number' ? value.duration_ms : 0
  const soundtrack = value.soundtrack === null || value.soundtrack === undefined
    ? null
    : motionSoundtrack(value.soundtrack, durationMs)
  if (value.soundtrack !== null && value.soundtrack !== undefined && !soundtrack) return null
  if (!Array.isArray(value.sources) || value.sources.length > 12) return null
  const sources: VisualArtifactSource[] = []
  for (const rawSource of value.sources) {
    const source = record(rawSource)
    if (!source || !string(source.tool_call_id, 120) || !source.tool_call_id || !string(source.query_summary, 500) || !source.query_summary) return null
    sources.push({ toolCallId: source.tool_call_id, querySummary: source.query_summary, verified: false })
  }
  if (kind !== 'dashboard' && sources.length) return null
  return {
    artifactId: value.artifact_id,
    kind,
    title: value.title,
    summary: value.summary,
    sourceHtml: typeof sourceHtml === 'string' ? sourceHtml : null,
    scene: sceneSpec,
    sources,
    durationMs: typeof value.duration_ms === 'number' ? value.duration_ms : null,
    soundtrack,
    revision: Number.isInteger(value.artifact_revision) && (value.artifact_revision as number) >= 1
      ? value.artifact_revision as number
      : revision,
  }
}

export function parseVisualArtifactBridgeMessage(raw: unknown): VisualArtifactBridgeMessage | null {
  const value = record(raw)
  if (!value || typeof value.type !== 'string') return null
  if (value.type === 'timeline') {
    const beats = motionTimeline(value.beats)
    return beats ? { type: 'timeline', beats } : null
  }
  if (value.type === 'ready' && typeof value.motionCanvas === 'boolean') {
    const canvasWidth = Number.isInteger(value.canvasWidth) && (value.canvasWidth as number) > 0 && (value.canvasWidth as number) <= 4096
      ? value.canvasWidth as number
      : undefined
    const canvasHeight = Number.isInteger(value.canvasHeight) && (value.canvasHeight as number) > 0 && (value.canvasHeight as number) <= 4096
      ? value.canvasHeight as number
      : undefined
    const frameRenderer = value.frameRenderer === true
      && canvasWidth !== undefined
      && canvasHeight !== undefined
      && canvasWidth * canvasHeight <= 8_294_400
    return {
      type: 'ready',
      motionCanvas: value.motionCanvas,
      ...(typeof value.frameRenderer === 'boolean' ? { frameRenderer } : {}),
      ...(canvasWidth !== undefined ? { canvasWidth } : {}),
      ...(canvasHeight !== undefined ? { canvasHeight } : {}),
    }
  }
  if (
    value.type === 'rendered_frame'
    && Number.isSafeInteger(value.requestId)
    && (value.requestId as number) >= 0
    && Number.isFinite(value.currentTimeMs)
    && typeof value.currentTimeMs === 'number'
    && value.currentTimeMs >= 0
    && typeof ImageBitmap !== 'undefined'
    && value.bitmap instanceof ImageBitmap
    && value.bitmap.width > 0
    && value.bitmap.height > 0
    && value.bitmap.width <= 4096
    && value.bitmap.height <= 4096
  ) {
    return { type: 'rendered_frame', requestId: value.requestId as number, currentTimeMs: value.currentTimeMs, bitmap: value.bitmap }
  }
  if (
    value.type === 'frame_error'
    && Number.isSafeInteger(value.requestId)
    && (value.requestId as number) >= 0
    && string(value.message, 500)
  ) return { type: 'frame_error', requestId: value.requestId as number, message: value.message }
  if (value.type === 'resize' && typeof value.height === 'number' && Number.isFinite(value.height) && value.height >= 160 && value.height <= 2000) {
    return { type: 'resize', height: value.height }
  }
  if (value.type === 'send_prompt' && string(value.prompt, 10_000) && value.prompt.trim()) {
    return { type: 'send_prompt', prompt: value.prompt.trim() }
  }
  if (value.type === 'playback' && Number.isFinite(value.currentTimeMs) && typeof value.currentTimeMs === 'number' && value.currentTimeMs >= 0 && ['playing', 'paused', 'ended'].includes(String(value.state))) {
    return { type: 'playback', currentTimeMs: value.currentTimeMs, state: value.state as 'playing' | 'paused' | 'ended' }
  }
  if (value.type === 'export_chunk' && typeof value.mimeType === 'string' && value.mimeType.startsWith('video/') && typeof value.final === 'boolean') {
    const bytes = value.bytes instanceof Uint8Array ? value.bytes : Array.isArray(value.bytes) && value.bytes.every((n) => Number.isInteger(n) && n >= 0 && n <= 255) ? Uint8Array.from(value.bytes) : null
    if (bytes && bytes.byteLength <= MAX_BRIDGE_CHUNK_BYTES) return { type: 'export_chunk', mimeType: value.mimeType, bytes, final: value.final }
  }
  if (value.type === 'export_status' && ['recording', 'complete', 'cancelled', 'error'].includes(String(value.state))) {
    const message = string(value.message, 500) ? value.message : undefined
    return { type: 'export_status', state: value.state as 'recording' | 'complete' | 'cancelled' | 'error', ...(message ? { message } : {}) }
  }
  return null
}
