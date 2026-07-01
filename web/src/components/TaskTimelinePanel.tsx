/**
 * TaskTimelinePanel — vertical task progress timeline.
 *
 * Renders session chapters as a vertical list of phases:
 *   ✓  completed  (all but the last)
 *   ⟳  active     (last chapter, when agent is working)
 *   ○  pending    (has no chapters yet)
 *
 * Clicking a phase scrolls AgentView to the chapter's anchor message.
 */

import { useEffect, useState } from 'react'
import { CheckCircle2, Circle, Loader2, Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useSessionChapters } from '@/hooks/useSessionChapters'
import type { Chapter } from '@/api/types'

interface TaskTimelinePanelProps {
  sessionId: string | null | undefined
  isWorking: boolean
  className?: string
}

type PhaseStatus = 'done' | 'active' | 'pending'

interface Phase {
  chapter: Chapter
  status: PhaseStatus
  elapsed: string | null
}

function formatDuration(ms: number): string {
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rem = s % 60
  return rem > 0 ? `${m}m ${rem}s` : `${m}m`
}

function computeElapsed(from: string, to: string | number): string | null {
  const start = new Date(from).getTime()
  if (isNaN(start)) return null
  const end = typeof to === 'number' ? to : new Date(to).getTime()
  if (isNaN(end)) return null
  return formatDuration(Math.max(0, end - start))
}

function scrollToChapter(chapter: Chapter) {
  if (!chapter.message_id) return
  const el = document.querySelector(`[data-chapter-anchor="${chapter.message_id}"]`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

function PhaseIcon({ status }: { status: PhaseStatus }) {
  if (status === 'done') {
    return <CheckCircle2 className="h-4 w-4 shrink-0 text-green-500" />
  }
  if (status === 'active') {
    return <Loader2 className="h-4 w-4 shrink-0 animate-spin text-amber-400" />
  }
  return <Circle className="h-4 w-4 shrink-0 text-(--color-text-muted)" />
}

function PhaseRow({ phase, isLast }: { phase: Phase; isLast: boolean }) {
  const { chapter, status, elapsed } = phase
  return (
    <button
      type="button"
      onClick={() => scrollToChapter(chapter)}
      className={cn(
        'group relative flex w-full items-start gap-3 py-2 px-3 text-left',
        'rounded-md transition-colors',
        'hover:bg-(--bg-hover)',
        status === 'active' && 'bg-(--bg-hover)',
      )}
    >
      {/* Connector line */}
      {!isLast && (
        <span
          className={cn(
            'absolute left-[22px] top-8 bottom-0 w-px',
            status === 'done' ? 'bg-green-500/30' : 'bg-(--border-subtle)',
          )}
        />
      )}

      <PhaseIcon status={status} />

      <div className="min-w-0 flex-1">
        <p
          className={cn(
            'text-xs font-medium leading-tight',
            status === 'active'
              ? 'text-(--color-text)'
              : status === 'done'
                ? 'text-(--color-text-muted)'
                : 'text-(--color-text-muted) opacity-60',
          )}
        >
          {chapter.title}
        </p>
        {chapter.summary && (
          <p className="mt-0.5 text-[11px] text-(--color-text-muted) leading-snug line-clamp-2">
            {chapter.summary}
          </p>
        )}
        {elapsed && (
          <p className="mt-1 flex items-center gap-1 text-[10px] text-(--color-text-muted) opacity-70">
            <Clock className="h-2.5 w-2.5" />
            {elapsed}
          </p>
        )}
      </div>
    </button>
  )
}

export function TaskTimelinePanel({
  sessionId,
  isWorking,
  className,
}: TaskTimelinePanelProps) {
  const { data: chapters = [], isLoading } = useSessionChapters(sessionId)

  // Tick once a second while working so the active step's elapsed time counts
  // up live (rather than freezing until the next chapters refetch).
  const [nowTs, setNowTs] = useState(() => Date.now())
  useEffect(() => {
    if (!isWorking) return
    const id = setInterval(() => setNowTs(Date.now()), 1000)
    return () => clearInterval(id)
  }, [isWorking])

  if (!sessionId) return null

  if (isLoading) {
    return (
      <div className={cn('flex items-center justify-center py-8', className)}>
        <Loader2 className="h-4 w-4 animate-spin text-(--color-text-muted)" />
      </div>
    )
  }

  if (chapters.length === 0) {
    return (
      <div className={cn('flex flex-col items-center justify-center py-8 px-4 text-center', className)}>
        <Circle className="mb-2 h-8 w-8 text-(--color-text-muted) opacity-40" />
        <p className="text-xs text-(--color-text-muted)">
          No progress milestones yet.
        </p>
        <p className="mt-1 text-[11px] text-(--color-text-muted) opacity-70">
          The agent creates milestones as it works through tasks.
        </p>
      </div>
    )
  }

  const phases: Phase[] = chapters.map((chapter, i) => {
    const isLast = i === chapters.length - 1
    const next = chapters[i + 1]
    const status: PhaseStatus = isLast && isWorking ? 'active' : 'done'

    // Active step ticks to "now"; a completed step measures to the next
    // chapter's start. A finished last step has no reliable end timestamp, so
    // we omit its elapsed rather than let it grow to now on every re-render.
    const elapsed =
      status === 'active'
        ? computeElapsed(chapter.created_at, nowTs)
        : next
          ? computeElapsed(chapter.created_at, next.created_at)
          : null

    return { chapter, status, elapsed }
  })

  const doneCount = phases.filter((p) => p.status === 'done').length
  const total = phases.length
  const progress = total > 0 ? Math.round((doneCount / total) * 100) : 0

  return (
    <div className={cn('flex flex-col', className)}>
      {/* Progress bar */}
      <div className="mx-3 mb-3 mt-1">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[10px] text-(--color-text-muted)">
            {doneCount}/{total} steps
          </span>
          <span className="text-[10px] text-(--color-text-muted)">{progress}%</span>
        </div>
        <div className="h-1 w-full rounded-full bg-(--border-subtle)">
          <div
            className="h-1 rounded-full bg-green-500 transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Phase list */}
      <div className="flex flex-col px-1">
        {phases.map((phase, i) => (
          <PhaseRow key={phase.chapter.id} phase={phase} isLast={i === phases.length - 1} />
        ))}
      </div>
    </div>
  )
}
