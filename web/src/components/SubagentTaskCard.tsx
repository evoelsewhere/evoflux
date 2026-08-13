/** SubagentTaskCard — durable lifecycle surface for a delegated team task. */
import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronUp } from 'lucide-react'

import { AgentLogo } from '@/components/AgentLogo'
import { useReducedMotion } from '@/hooks/useReducedMotion'
import type { DelegationDisplayStatus } from '@/lib/delegation-activity'
import { panelTransition, useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'

export interface SubagentTaskCardProps {
  agent: string
  title: string
  status?: DelegationDisplayStatus | 'idle'
  activity?: string
  handoff?: Record<string, unknown> | null
  taskId?: string
  startedAt?: number
  completedAt?: number
  isolation?: 'shared' | 'worktree'
  repoCount?: number
  onFocus?: () => void
  /** When false, render a non-interactive header (avoids nested buttons). */
  interactive?: boolean
  className?: string
}

function formatElapsed(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1_000))
  if (totalSeconds < 60) return `${totalSeconds}s`
  const minutes = Math.floor(totalSeconds / 60)
  return `${minutes}m ${totalSeconds % 60}s`
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string' && item.length > 0)
    : []
}

export function SubagentTaskCard({
  agent,
  title,
  status = 'running',
  activity,
  handoff,
  taskId,
  startedAt,
  completedAt,
  isolation,
  repoCount,
  onFocus,
  interactive = true,
  className,
}: SubagentTaskCardProps) {
  const reducedMotion = useReducedMotion()
  const preset = useMotionPreset()
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const isActive = status === 'queued' || status === 'running'

  useEffect(() => {
    if (!isActive || !startedAt) return
    const interval = window.setInterval(() => setNow(Date.now()), 1_000)
    return () => window.clearInterval(interval)
  }, [isActive, startedAt])

  const summary = typeof handoff?.summary === 'string' ? handoff.summary : null
  const findings = stringList(handoff?.findings)
  const evidence = stringList(handoff?.evidence)
  const nextActions = stringList(handoff?.next_actions)
  const rawData = typeof handoff?.raw_data === 'string' ? handoff.raw_data : null
  const confidence = typeof handoff?.confidence === 'number' ? handoff.confidence : null
  const verification = handoff?.verification && typeof handoff.verification === 'object'
    ? handoff.verification as Record<string, unknown>
    : null
  const hasDetails = findings.length > 0 || evidence.length > 0 || nextActions.length > 0 || Boolean(rawData)
  const elapsedEnd = isActive ? now : completedAt
  const elapsed = startedAt && elapsedEnd !== undefined
    ? formatElapsed(Math.max(0, elapsedEnd - startedAt))
    : null

  const headerContent = (
    <>
      <AgentLogo
        name={agent}
        size="xs"
        className="mt-0.5"
        statusClassName={cn(
          status === 'running' && 'bg-(--color-accent)',
          status === 'running' && reducedMotion !== true && 'animate-pulse',
          status === 'done' && 'bg-(--color-success)',
          status === 'review' && 'bg-(--color-warning)',
          status === 'paused' && 'bg-(--color-warning)',
          status === 'queued' && 'bg-(--color-text-subtle)',
          status === 'error' && 'bg-(--color-error)',
          status === 'idle' && 'bg-(--color-text-subtle)',
        )}
      />
      <div className="min-w-0 flex-1">
        <p className="truncate font-mono text-[11px] font-semibold text-(--color-text)">
          Task → {agent}
        </p>
        <p className="mt-0.5 line-clamp-2 text-xs text-(--color-text-muted)">{title}</p>
        {activity && !summary && (
          <p
            className={cn(
              'mt-1 truncate text-[11px]',
              status === 'running' && 'text-(--color-accent)',
              status === 'done' && 'text-(--color-success)',
              status === 'review' && 'text-(--color-warning)',
              status === 'paused' && 'text-(--color-warning)',
              status === 'error' && 'text-(--color-error)',
              (status === 'queued' || status === 'idle') && 'text-(--color-text-subtle)',
            )}
            title={activity}
          >
            {activity}
          </p>
        )}
      </div>
      <span className="flex shrink-0 items-center gap-1">
        {isolation === 'worktree' && (
          <span className="rounded-xs bg-(--bg-key) px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-(--color-text-subtle)">
            worktree{repoCount && repoCount > 1 ? ` ×${repoCount}` : ''}
          </span>
        )}
        <span
          className={cn(
            'rounded-xs px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide',
            status === 'running' && 'bg-(--color-accent)/10 text-(--color-accent)',
            status === 'done' && 'bg-(--color-success)/10 text-(--color-success)',
            status === 'review' && 'bg-(--color-warning)/10 text-(--color-warning)',
            status === 'paused' && 'bg-(--color-warning)/10 text-(--color-warning)',
            status === 'error' && 'bg-(--color-error-subtle) text-(--color-error)',
            (status === 'queued' || status === 'idle') && 'bg-(--bg-key) text-(--color-text-subtle)',
          )}
        >
          {status}
        </span>
        {elapsed && (
          <span
            aria-label={`Elapsed ${elapsed}`}
            className="min-w-9 font-mono text-[10px] tabular-nums text-(--color-text-subtle)"
          >
            {elapsed}
          </span>
        )}
      </span>
    </>
  )

  const rootClasses = cn(
    'w-full overflow-hidden rounded-md border border-(--color-border-subtle) bg-(--bg-page) text-left transition-colors',
    status === 'running' && 'border-(--color-accent)/25',
    status === 'review' && 'border-(--color-warning)/30',
    status === 'paused' && 'border-(--color-warning)/30',
    status === 'done' && 'border-(--color-success)/25',
    status === 'error' && 'border-(--color-error)/35 bg-(--color-error-subtle)',
    className,
  )
  const headerClasses = cn(
    'flex w-full items-start gap-2 px-2.5 py-2 text-left',
    interactive && 'focus-ring-control hover:bg-(--bg-key)',
  )

  return (
    <div className={rootClasses} title={taskId ? `Task ${taskId}` : undefined}>
      {interactive ? (
        <button
          type="button"
          onClick={onFocus}
          className={headerClasses}
          title={taskId ? `Open ${agent} · Task ${taskId}` : `Open ${agent}`}
        >
          {headerContent}
        </button>
      ) : (
        <div className={headerClasses}>{headerContent}</div>
      )}

      {summary && (
        <div className="border-t border-(--color-border-subtle) px-2.5 py-2">
          <div className="flex items-start gap-2">
            <p data-i18n-ignore className="min-w-0 flex-1 text-xs leading-relaxed text-(--color-text)">
              {summary}
            </p>
            {hasDetails && (
              <button
                type="button"
                onClick={() => setDetailsOpen((open) => !open)}
                aria-expanded={detailsOpen}
                aria-label={detailsOpen ? 'Collapse handoff details' : 'Expand handoff details'}
                className="flex size-5 shrink-0 items-center justify-center rounded-md border border-(--color-border) text-(--color-text-muted) transition-colors hover:text-(--color-text) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)"
              >
                {detailsOpen ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
              </button>
            )}
          </div>

          {(confidence !== null || verification) && (
            <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11px] text-(--color-text-muted)">
              {confidence !== null && (
                <span className="flex items-center gap-1.5">
                  Confidence
                  <span className="h-1 w-12 overflow-hidden rounded-full bg-(--color-border)">
                    <span
                      className={cn(
                        'block h-full rounded-full',
                        confidence >= 0.8
                          ? 'bg-(--color-success)'
                          : confidence >= 0.5
                            ? 'bg-(--color-warning)'
                            : 'bg-(--color-error)',
                      )}
                      style={{ width: `${Math.round(confidence * 100)}%` }}
                    />
                  </span>
                  <span className="font-mono text-(--color-text-2)">{Math.round(confidence * 100)}%</span>
                </span>
              )}
              {verification && (
                <span className={cn(
                  'flex items-center gap-1',
                  verification.verified ? 'text-(--color-success)' : 'text-(--color-warning)',
                )}>
                  {verification.verified
                    ? <CheckCircle2 size={11} aria-hidden="true" />
                    : <AlertTriangle size={11} aria-hidden="true" />}
                  {verification.verified
                    ? String(verification.method ?? 'Verified')
                    : 'Not verified'}
                </span>
              )}
            </div>
          )}

          <AnimatePresence initial={false}>
            {detailsOpen && hasDetails && (
              <motion.div
                initial={preset.intensity === 'reduced' ? false : { height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={preset.intensity === 'reduced' ? undefined : { height: 0, opacity: 0 }}
                transition={panelTransition(preset)}
                className="overflow-hidden"
              >
                <div className="mt-2 space-y-2 border-t border-(--color-border-subtle) pt-2 text-[11px]">
                  {findings.length > 0 && (
                    <div>
                      <p className="font-semibold text-(--color-text-2)">Findings</p>
                      <ul className="list-inside list-disc text-(--color-text)">
                        {findings.map((item, index) => <li key={index}>{item}</li>)}
                      </ul>
                    </div>
                  )}
                  {evidence.length > 0 && (
                    <div>
                      <p className="font-semibold text-(--color-text-2)">Evidence</p>
                      <ul className="list-inside list-disc text-(--color-text-muted)">
                        {evidence.map((item, index) => <li key={index}>{item}</li>)}
                      </ul>
                    </div>
                  )}
                  {nextActions.length > 0 && (
                    <div>
                      <p className="font-semibold text-(--color-text-2)">Next actions</p>
                      <ul className="list-inside list-disc text-(--color-text)">
                        {nextActions.map((item, index) => <li key={index}>{item}</li>)}
                      </ul>
                    </div>
                  )}
                  {rawData && <p className="whitespace-pre-wrap text-(--color-text-muted)">{rawData}</p>}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </div>
  )
}
