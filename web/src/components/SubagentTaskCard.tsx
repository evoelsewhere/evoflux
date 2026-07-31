/**
 * SubagentTaskCard — dens Cursor-like chrome for a delegated team task.
 */
import { Orbit } from 'lucide-react'

import { cn } from '@/lib/utils'
import { useReducedMotion } from '@/hooks/useReducedMotion'

export interface SubagentTaskCardProps {
  agent: string
  title: string
  status?: 'running' | 'done' | 'idle'
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
  isolation,
  repoCount,
  onFocus,
  interactive = true,
  className,
}: SubagentTaskCardProps) {
  const reducedMotion = useReducedMotion()
  const content = (
    <>
      <Orbit
        size={14}
        className={cn(
          'mt-0.5 shrink-0',
          status === 'running' ? 'text-(--color-accent)' : 'text-(--color-text-muted)',
          status === 'running' && reducedMotion !== true && 'animate-spin',
        )}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <p className="truncate font-mono text-[11px] font-semibold text-(--color-text)">
          Task → {agent}
        </p>
        <p className="mt-0.5 line-clamp-2 text-xs text-(--color-text-muted)">{title}</p>
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
    interactive && 'focus-ring-control hover:bg-(--bg-key)',
    className,
  )

  if (!interactive) {
    return <div className={classes}>{content}</div>
  }

  return (
    <button type="button" onClick={onFocus} className={classes}>
      {content}
    </button>
  )
}
