/** SubagentTaskCard — compact chrome for a delegated team task. */
import { AgentLogo } from '@/components/AgentLogo'
import { cn } from '@/lib/utils'
import { useReducedMotion } from '@/hooks/useReducedMotion'
import type { DelegationDisplayStatus } from '@/lib/delegation-activity'

export interface SubagentTaskCardProps {
  agent: string
  title: string
  status?: DelegationDisplayStatus | 'idle'
  activity?: string
  taskId?: string
  isolation?: 'shared' | 'worktree'
  repoCount?: number
  onFocus?: () => void
  /** When false, render a non-interactive div (avoids nested buttons). */
  interactive?: boolean
  className?: string
}

export function SubagentTaskCard({
  agent,
  title,
  status = 'running',
  activity,
  taskId,
  isolation,
  repoCount,
  onFocus,
  interactive = true,
  className,
}: SubagentTaskCardProps) {
  const reducedMotion = useReducedMotion()
  const content = (
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
        {activity && (
          <p
            className={cn(
              'mt-1 truncate text-[11px]',
              status === 'running' && 'text-(--color-accent)',
              status === 'done' && 'text-(--color-success)',
              status === 'review' && 'text-(--color-warning)',
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
        <span className="rounded-xs bg-(--bg-key) px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-(--color-text-subtle)">
          {status}
        </span>
      </span>
    </>
  )

  const classes = cn(
    'flex w-full items-start gap-2 rounded-md border border-(--color-border-subtle) bg-(--bg-page) px-2.5 py-2 text-left transition-colors',
    status === 'running' && 'border-(--color-accent)/25',
    status === 'review' && 'border-(--color-warning)/30',
    status === 'error' && 'border-(--color-error)/35 bg-(--color-error-subtle)',
    interactive && 'focus-ring-control hover:bg-(--bg-key)',
    className,
  )

  if (!interactive) {
    return <div className={classes} title={taskId ? `Task ${taskId}` : undefined}>{content}</div>
  }

  return (
    <button
      type="button"
      onClick={onFocus}
      className={classes}
      title={taskId ? `Open ${agent} · Task ${taskId}` : `Open ${agent}`}
    >
      {content}
    </button>
  )
}
