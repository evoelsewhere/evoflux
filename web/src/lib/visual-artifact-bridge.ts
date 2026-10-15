import type { Scene3DSpec, VisualArtifactKind, VisualArtifactPayload, VisualArtifactSource } from '@/api/types'

export type VisualArtifactBridgeMessage =
  | { type: 'ready'; motionCanvas: boolean }
  | { type: 'resize'; height: number }
  | { type: 'send_prompt'; prompt: string }
  | { type: 'playback'; currentTimeMs: number; state: 'playing' | 'paused' | 'ended' }
  | { type: 'export_chunk'; mimeType: string; bytes: Uint8Array; final: boolean }

const MAX_SOURCE_BYTES = 200_000
const MAX_BRIDGE_CHUNK_BYTES = 64_000

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function string(value: unknown, max: number): value is string {
  return typeof value === 'string' && value.length <= max
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
    revision,
  }
}

export function parseVisualArtifactBridgeMessage(raw: unknown): VisualArtifactBridgeMessage | null {
  const value = record(raw)
  if (!value || typeof value.type !== 'string') return null
  if (value.type === 'ready' && typeof value.motionCanvas === 'boolean') return { type: 'ready', motionCanvas: value.motionCanvas }
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
  return null
}
