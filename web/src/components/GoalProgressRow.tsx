import { Pause, Play, Target, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { GoalResponse } from '@/api/types'

interface GoalProgressRowProps {
  goal: GoalResponse
  onCommand: (command: string) => void
}

const statusLabels: Record<GoalResponse['status'], string> = {
  active: 'Running',
  paused: 'Paused',
  complete: 'Complete',
  blocked: 'Blocked',
}

function formatTokens(value: number): string {
  return new Intl.NumberFormat('en-US', {
    notation: value >= 10_000 ? 'compact' : 'standard',
    maximumFractionDigits: 1,
  }).format(value)
}

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m`
  return `${total}s`
}

export function GoalProgressRow({ goal, onCommand }: GoalProgressRowProps) {
  const progress = goal.token_budget
    ? Math.min((goal.tokens_used / goal.token_budget) * 100, 100)
    : null
  const usageLabel = goal.token_budget
    ? `${formatTokens(goal.tokens_used)} / ${formatTokens(goal.token_budget)} tokens`
    : `${formatTokens(goal.tokens_used)} tokens`

  return (
    <section
      aria-label="Session goal"
      className="mx-auto mb-1.5 max-w-4xl rounded-xl border border-(--color-border) bg-(--color-surface) px-3 py-2 shadow-sm"
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <Target size={14} className="shrink-0 text-(--color-accent)" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2 text-xs">
            <span className="truncate font-medium text-(--color-text)" title={goal.objective}>
              {goal.objective}
            </span>
            <span className="shrink-0 rounded-full bg-(--bg-key) px-1.5 py-0.5 text-[10px] font-medium text-(--color-text-muted)">
              {statusLabels[goal.status]}
            </span>
          </div>
          <div className="mt-1 flex items-center gap-2 text-[10px] text-(--color-text-subtle)">
            <span className="tabular-nums">{usageLabel}</span>
            <span aria-hidden="true">·</span>
            <span className="tabular-nums">{formatDuration(goal.time_used_seconds)}</span>
            {goal.blocker_streak > 0 && (
              <>
                <span aria-hidden="true">·</span>
                <span>blocker {goal.blocker_streak}/3</span>
              </>
            )}
          </div>
          {progress !== null && (
            <div
              role="progressbar"
              aria-label="Goal token budget"
              aria-valuemin={0}
              aria-valuemax={goal.token_budget ?? undefined}
              aria-valuenow={Math.min(goal.tokens_used, goal.token_budget ?? goal.tokens_used)}
              className="mt-1.5 h-1 overflow-hidden rounded-full bg-(--bg-key)"
            >
              <div
                className="h-full rounded-full bg-(--color-accent) transition-[width] duration-(--motion-base)"
                style={{ width: `${progress}%` }}
              />
            </div>
          )}
        </div>
        {goal.status === 'active' && (
          <Button type="button" variant="ghost" size="icon-xs" onClick={() => onCommand('/goal:pause')} aria-label="Pause goal" title="Pause goal">
            <Pause aria-hidden="true" />
          </Button>
        )}
        {goal.status === 'paused' && (
          <Button type="button" variant="ghost" size="icon-xs" onClick={() => onCommand('/goal:resume')} aria-label="Resume goal" title="Resume goal">
            <Play aria-hidden="true" />
          </Button>
        )}
        <Button type="button" variant="ghost" size="icon-xs" onClick={() => onCommand('/goal:stop')} aria-label="Remove goal" title="Remove goal">
          <X aria-hidden="true" />
        </Button>
      </div>
    </section>
  )
}
