import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react'
import { Box, ExternalLink } from 'lucide-react'
import type { ContentBlock } from '@/api/types'
import { useUIStore } from '@/stores/useUIStore'
import { getMotionRenderSnapshot, publishMotionRenderSnapshot, subscribeMotionRender } from '@/lib/motion-render-store'

function useMotionRenderSnapshot(artifactId: string, revision: number) {
  const subscribe = useCallback((notify: () => void) => (
    subscribeMotionRender(artifactId, revision, () => notify())
  ), [artifactId, revision])
  const getSnapshot = useCallback(() => getMotionRenderSnapshot(artifactId, revision), [artifactId, revision])
  return useSyncExternalStore(subscribe, getSnapshot, () => null)
}

function motionStatus(snapshot: NonNullable<ReturnType<typeof useMotionRenderSnapshot>>): string {
  if (snapshot.status === 'rendering') {
    return snapshot.totalFrames === null
      ? 'Recording video · frame count unavailable'
      : `Rendering ${snapshot.completedFrames} / ${snapshot.totalFrames} frames${snapshot.fps ? ` · ${snapshot.fps} fps` : ''}`
  }
  if (snapshot.status === 'complete') {
    return snapshot.totalFrames === null
      ? 'Video recording complete · frame count unavailable'
      : `Video render complete · ${snapshot.completedFrames} / ${snapshot.totalFrames} frames`
  }
  if (snapshot.status === 'cancelled') return 'Video render cancelled'
  if (snapshot.status === 'failed') return 'Video render failed'
  return 'Motion timeline ready'
}

const KIND_LABELS = {
  dashboard: 'Dashboard',
  motion: 'Animated explainer',
  scene3d: '3D scene',
} as const

const PHASE_LABELS = {
  planning: 'Planning the story',
  storyboard: 'Building the storyboard',
  style_samples: 'Checking visual style',
  composing: 'Composing scenes',
  rendering_samples: 'Rendering sample frames',
  reviewing: 'Reviewing selected frames',
  revising: 'Revising the animation',
  final_render: 'Rendering final video',
  encoding: 'Encoding video',
  audio: 'Preparing soundtrack',
} as const

function lifecycleStatus(progress: NonNullable<ContentBlock['motionProgress']>): string {
  if (progress.status === 'complete') return 'Motion job complete'
  if (progress.status === 'cancelled') return 'Motion job cancelled'
  if (progress.status === 'failed') return 'Motion job failed'
  if (progress.status === 'interrupted') return 'Motion job interrupted'
  return PHASE_LABELS[progress.phase]
}

export function VisualArtifactRenderer({ block }: { block: ContentBlock }) {
  const artifact = block.visualArtifact
  const lifecycle = block.motionProgress
  const sessionId = useUIStore((state) => state.workbenchSessionId)
  const tabs = useUIStore((state) => state.workbenchTabs)
  const openWorkbenchTool = useUIStore((state) => state.openWorkbenchTool)
  const updateWorkbenchTab = useUIStore((state) => state.updateWorkbenchTab)
  const reviewRequestSequence = useRef(0)
  const handledSampleRequestId = useRef<string | null>(null)
  const motionSnapshot = useMotionRenderSnapshot(
    artifact?.artifactId ?? lifecycle?.artifactId ?? '',
    artifact?.revision ?? lifecycle?.artifactRevision ?? 0,
  )

  useEffect(() => {
    if (!artifact) return
    if (artifact.kind === 'motion' && !getMotionRenderSnapshot(artifact.artifactId, artifact.revision)) {
      publishMotionRenderSnapshot({
        artifactId: artifact.artifactId,
        revision: artifact.revision,
        renderId: `artifact-${artifact.artifactId}-r${artifact.revision}`,
        status: 'idle',
        completedFrames: 0,
        totalFrames: null,
        fps: null,
        lastCompletedIndex: null,
        currentTimeMs: 0,
        currentFrameUrl: null,
        beats: [],
        samples: [],
        audioStatus: 'not_requested',
      })
    }
    for (const tab of tabs) {
      if (
        tab.tool === 'visual-artifact'
        && tab.sessionId === sessionId
        && tab.artifact?.artifactId === artifact.artifactId
        && tab.artifact.revision < artifact.revision
      ) {
        updateWorkbenchTab(tab.id, { title: artifact.title, artifact })
      }
    }
  }, [artifact, sessionId, tabs, updateWorkbenchTab])

  useEffect(() => {
    if (
      !artifact
      || artifact.kind !== 'motion'
      || !sessionId
      || !lifecycle?.sampleRequestId
      || lifecycle.artifactRevision !== artifact.revision
      || handledSampleRequestId.current === lifecycle.sampleRequestId
    ) return
    handledSampleRequestId.current = lifecycle.sampleRequestId
    openWorkbenchTool('visual-artifact', {
      title: artifact.title,
      artifact,
      motionSampleReviewRequest: {
        id: `${lifecycle.jobId}:${lifecycle.sampleRequestId}`,
        jobId: lifecycle.jobId,
        sampleRequestId: lifecycle.sampleRequestId,
        samples: lifecycle.selectedSamples,
      },
    })
  }, [artifact, lifecycle, openWorkbenchTool, sessionId])

  if (!artifact && !lifecycle) return null
  const title = artifact?.title ?? block.title ?? lifecycle?.beat?.title ?? 'Motion explainer'
  const exactFrames = artifact?.kind === 'motion' ? motionSnapshot : null
  const frameCounts = exactFrames && exactFrames.status === 'rendering'
    ? { completed: exactFrames.completedFrames, total: exactFrames.totalFrames, fps: exactFrames.fps }
    : lifecycle?.frames
      ? { completed: lifecycle.frames.completed, total: lifecycle.frames.total, fps: lifecycle.frames.fps }
      : null
  return (
    <div className="my-2 flex min-w-0 flex-wrap items-center gap-3 rounded-xl border border-(--color-border-subtle) bg-(--bg-card) p-3">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-(--color-accent)/10 text-(--color-accent)">
        <Box size={18} aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <h3 className="truncate text-sm font-medium text-(--color-text)">{title}</h3>
          <span className="shrink-0 rounded-md border border-(--color-border-subtle) px-1.5 py-0.5 text-[10px] text-(--color-text-muted)">
            {artifact ? KIND_LABELS[artifact.kind] : 'Animated explainer'}
          </span>
        </div>
        {artifact && <p className="mt-0.5 line-clamp-2 text-xs text-(--color-text-subtle)">{artifact.summary}</p>}
      </div>
      {artifact && (
        <button
          type="button"
          onClick={() => openWorkbenchTool('visual-artifact', { title: artifact.title, artifact })}
          className="ml-auto flex h-8 shrink-0 items-center gap-1.5 rounded-lg bg-(--color-accent) px-2.5 text-xs font-medium text-white transition-colors hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)"
        >
          <span>Open in Workbench</span>
          <ExternalLink size={13} aria-hidden="true" />
        </button>
      )}
      {(artifact?.kind === 'motion' || lifecycle) && (
        <div className="min-w-0 basis-full border-t border-(--color-border-subtle) pt-2" aria-label="Motion render progress">
          {frameCounts?.total !== null && frameCounts?.total !== undefined && (
            <div
              role="progressbar"
              aria-label="Rendered video frames"
              aria-valuemin={0}
              aria-valuemax={frameCounts.total}
              aria-valuenow={frameCounts.completed}
              className="mb-1 h-1.5 overflow-hidden rounded-full bg-(--bg-key)"
            >
              <div className="h-full rounded-full bg-(--color-accent)" style={{ width: `${Math.min(100, (frameCounts.completed / frameCounts.total) * 100)}%` }} />
            </div>
          )}
          <p role="status" aria-live="polite" className="text-xs text-(--color-text-subtle)">
            {exactFrames && exactFrames.status !== 'idle'
              ? motionStatus(exactFrames)
              : lifecycle
                ? `${lifecycleStatus(lifecycle)}${lifecycle.beat ? ` · Beat ${lifecycle.beat.index + 1}/${lifecycle.beat.total}: ${lifecycle.beat.title}` : ''}${lifecycle.iteration ? ` · Review ${lifecycle.iteration.current}/${lifecycle.iteration.budget}` : ''}${frameCounts ? ` · ${frameCounts.completed} / ${frameCounts.total ?? 'unknown'} frames${frameCounts.fps ? ` · ${frameCounts.fps} fps` : ''}` : ''}`
                : 'Motion timeline ready'}
          </p>
          {exactFrames && exactFrames.samples.length > 0 && artifact && (
            <div className="mt-2 flex gap-2 overflow-x-auto" aria-label="Representative motion frames">
              {exactFrames.samples.slice(0, 4).map((sample) => {
                const beatTitle = exactFrames.beats.find((beat) => beat.id === sample.beatId)?.title ?? 'Preview'
                return (
                  <button
                    key={sample.sampleId}
                    type="button"
                    aria-label={`Review frame ${sample.frameIndex + 1} in Workbench`}
                    title={`${beatTitle} · frame ${sample.frameIndex + 1} · ${(sample.timestampMs / 1000).toFixed(2)}s`}
                    onClick={() => {
                      reviewRequestSequence.current += 1
                      openWorkbenchTool('visual-artifact', {
                        title: artifact.title,
                        artifact,
                        motionReviewRequest: {
                          id: reviewRequestSequence.current,
                          frameIndex: sample.frameIndex,
                          timestampMs: sample.timestampMs,
                        },
                      })
                    }}
                    className="w-28 shrink-0 overflow-hidden rounded-lg border border-(--color-border) text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)"
                  >
                    <img src={sample.objectUrl} alt={`${beatTitle}, frame ${sample.frameIndex + 1}, ${(sample.timestampMs / 1000).toFixed(2)} seconds`} className="aspect-video w-full object-cover" />
                    <span className="block truncate px-1.5 py-1 text-[10px] text-(--color-text-subtle)">{beatTitle} · frame {sample.frameIndex + 1}</span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
