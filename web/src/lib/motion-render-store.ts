import type { MotionTimelineBeat } from '@/lib/visual-artifact-bridge'

export type MotionRenderStatus = 'idle' | 'rendering' | 'complete' | 'cancelled' | 'failed'
export type MotionAudioStatus = 'not_requested' | 'unavailable' | 'pending' | 'rendering' | 'included'
export type MotionReviewSampleRole = 'style' | 'key_state' | 'before_transition' | 'after_transition' | 'impact'

export interface MotionReviewSample {
  sampleId: string
  beatId: string
  frameIndex: number
  timestampMs: number
  role: MotionReviewSampleRole
  objectUrl: string
}

export interface MotionRenderSnapshot {
  artifactId: string
  revision: number
  renderId: string
  status: MotionRenderStatus
  completedFrames: number
  totalFrames: number | null
  fps: number | null
  lastCompletedIndex: number | null
  currentTimeMs: number
  currentFrameUrl: string | null
  beats: MotionTimelineBeat[]
  samples: MotionReviewSample[]
  audioStatus: MotionAudioStatus
}

type Listener = (snapshot: MotionRenderSnapshot | null) => void

const MAX_PREVIEW_SAMPLES = 12
const MAX_RENDER_SNAPSHOTS = 32
const snapshots = new Map<string, MotionRenderSnapshot>()
const listeners = new Map<string, Set<Listener>>()

function artifactKey(artifactId: string): string {
  return artifactId
}

function subscriptionKey(artifactId: string, revision: number): string {
  return `${artifactId}\u0000${revision}`
}

function revokeObjectUrls(urls: Array<string | null | undefined>): void {
  const unique = new Set(urls.filter((url): url is string => typeof url === 'string' && url.startsWith('blob:')))
  for (const url of unique) URL.revokeObjectURL(url)
}

function releaseSnapshot(snapshot: MotionRenderSnapshot): void {
  revokeObjectUrls([snapshot.currentFrameUrl, ...snapshot.samples.map((sample) => sample.objectUrl)])
}

function notify(artifactId: string, revision: number, snapshot: MotionRenderSnapshot | null): void {
  const subscribers = listeners.get(subscriptionKey(artifactId, revision))
  if (!subscribers) return
  for (const listener of subscribers) listener(snapshot)
}

function isValidSnapshot(snapshot: MotionRenderSnapshot): boolean {
  return Boolean(snapshot.artifactId)
    && Number.isSafeInteger(snapshot.revision)
    && snapshot.revision > 0
    && Boolean(snapshot.renderId)
    && Number.isSafeInteger(snapshot.completedFrames)
    && snapshot.completedFrames >= 0
    && (snapshot.totalFrames === null || (Number.isSafeInteger(snapshot.totalFrames) && snapshot.totalFrames > 0))
    && (snapshot.totalFrames === null || snapshot.completedFrames <= snapshot.totalFrames)
    && (snapshot.fps === null || (Number.isFinite(snapshot.fps) && snapshot.fps > 0))
    && (snapshot.lastCompletedIndex === null || (Number.isSafeInteger(snapshot.lastCompletedIndex) && snapshot.lastCompletedIndex >= 0))
    && Number.isFinite(snapshot.currentTimeMs)
    && snapshot.currentTimeMs >= 0
}

function normalizeSamples(samples: MotionReviewSample[]): MotionReviewSample[] | null {
  if (!Array.isArray(samples)) return null
  const seen = new Set<string>()
  const normalized: MotionReviewSample[] = []
  for (const sample of samples) {
    if (
      !sample
      || typeof sample.sampleId !== 'string'
      || !sample.sampleId
      || typeof sample.beatId !== 'string'
      || !Number.isSafeInteger(sample.frameIndex)
      || sample.frameIndex < 0
      || !Number.isFinite(sample.timestampMs)
      || sample.timestampMs < 0
      || !['style', 'key_state', 'before_transition', 'after_transition', 'impact'].includes(sample.role)
      || typeof sample.objectUrl !== 'string'
      || !sample.objectUrl.startsWith('blob:')
      || seen.has(sample.sampleId)
    ) return null
    seen.add(sample.sampleId)
    normalized.push({ ...sample })
  }
  return normalized
}

export function getMotionRenderSnapshot(artifactId: string, revision: number): MotionRenderSnapshot | null {
  const snapshot = snapshots.get(artifactKey(artifactId))
  return snapshot?.revision === revision ? snapshot : null
}

export function subscribeMotionRender(
  artifactId: string,
  revision: number,
  listener: Listener,
): () => void {
  const key = subscriptionKey(artifactId, revision)
  const subscribers = listeners.get(key) ?? new Set<Listener>()
  subscribers.add(listener)
  listeners.set(key, subscribers)
  listener(getMotionRenderSnapshot(artifactId, revision))
  return () => {
    subscribers.delete(listener)
    if (subscribers.size === 0) listeners.delete(key)
  }
}

/** Store the newest state for one artifact revision and release evicted preview URLs. */
export function publishMotionRenderSnapshot(snapshot: MotionRenderSnapshot): boolean {
  if (!isValidSnapshot(snapshot)) return false
  const samples = normalizeSamples(snapshot.samples)
  if (!samples) return false

  const key = artifactKey(snapshot.artifactId)
  const previous = snapshots.get(key)
  if (previous && snapshot.revision < previous.revision) return false

  const startsNewRun = previous !== undefined
    && (snapshot.revision > previous.revision || snapshot.renderId !== previous.renderId)
  if (previous && !startsNewRun) {
    if (snapshot.completedFrames < previous.completedFrames) return false
    if (snapshot.totalFrames !== previous.totalFrames) return false
  }

  const cappedSamples = samples.slice(0, MAX_PREVIEW_SAMPLES)
  const terminalSnapshot = snapshot.status === 'cancelled' || snapshot.status === 'failed'
    ? { ...snapshot, samples: [], currentFrameUrl: null }
    : { ...snapshot, samples: cappedSamples }

  if (snapshot.status === 'cancelled' || snapshot.status === 'failed') {
    revokeObjectUrls([snapshot.currentFrameUrl, ...samples.map((sample) => sample.objectUrl)])
  }

  if (previous && (startsNewRun || previous.revision !== snapshot.revision)) {
    releaseSnapshot(previous)
    notify(previous.artifactId, previous.revision, null)
  } else if (previous) {
    const retained = new Set([
      terminalSnapshot.currentFrameUrl,
      ...terminalSnapshot.samples.map((sample) => sample.objectUrl),
    ])
    revokeObjectUrls([
      previous.currentFrameUrl,
      ...previous.samples.map((sample) => sample.objectUrl),
    ].filter((url) => url && !retained.has(url)))
  }

  const next = { ...terminalSnapshot, samples: terminalSnapshot.samples.slice() }
  snapshots.delete(key)
  snapshots.set(key, next)
  if (snapshot.status !== 'cancelled' && snapshot.status !== 'failed' && samples.length > cappedSamples.length) {
    revokeObjectUrls(samples.slice(MAX_PREVIEW_SAMPLES)
      .map((sample) => sample.objectUrl)
      .filter((url) => url !== next.currentFrameUrl))
  }

  while (snapshots.size > MAX_RENDER_SNAPSHOTS) {
    const [oldestKey, oldest] = snapshots.entries().next().value ?? []
    if (!oldestKey || !oldest) break
    snapshots.delete(oldestKey)
    releaseSnapshot(oldest)
    notify(oldest.artifactId, oldest.revision, null)
  }

  notify(snapshot.artifactId, snapshot.revision, next)
  return true
}
