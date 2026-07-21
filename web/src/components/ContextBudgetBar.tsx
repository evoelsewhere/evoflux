/**
 * ContextBudgetBar — compact token-usage bar for the chat topbar.
 *
 * Shows:  [████████░░░] 68%  with color transitions at 80% and 95%.
 * A tooltip explains the usage and warns when summarization is near.
 *
 * Intended to sit beside the existing TokenMeter inside AgentTopbar or as
 * a standalone element in any header.
 */

import { cn } from '@/lib/utils'

// Typical context windows by model family (tokens). Used only when `max` is
// not explicitly provided — the caller should pass the real limit when known.
const DEFAULT_CONTEXT_MAX = 200_000

export interface ContextBudgetBarProps {
  /** Tokens consumed (input + output + cached). */
  used: number
  /** Context window ceiling; defaults to 200 000 (Sonnet/Opus). */
  max?: number
  className?: string
  /** Show the percentage label inline. Defaults to true. */
  showLabel?: boolean
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`
  return String(n)
}

export function ContextBudgetBar({
  used,
  max = DEFAULT_CONTEXT_MAX,
  className,
  showLabel = true,
}: ContextBudgetBarProps) {
  const pct = Math.min(100, Math.round((used / max) * 100))
  const isDanger = pct >= 95
  const isWarn = pct >= 80

  const barColor = isDanger
    ? 'bg-red-500'
    : isWarn
      ? 'bg-amber-400'
      : 'bg-(--accent-blue)'

  const tooltip = isDanger
    ? `Context ${pct}% full — auto-summarization imminent (${formatTokens(used)} / ${formatTokens(max)})`
    : isWarn
      ? `Context ${pct}% full — summarization may trigger soon (${formatTokens(used)} / ${formatTokens(max)})`
      : `Context ${pct}% used (${formatTokens(used)} / ${formatTokens(max)})`

  return (
    <div
      className={cn('inline-flex h-8 items-center gap-1.5 rounded-md px-2', className)}
      title={tooltip}
      aria-label={tooltip}
    >
      {/* Bar track */}
      <div className="relative h-1.5 w-14 overflow-hidden rounded-full bg-(--border-subtle)">
        <div
          className={cn('absolute inset-y-0 left-0 rounded-full transition-all duration-700', barColor)}
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Percentage label */}
      {showLabel && (
        <span
          className={cn(
            'font-mono text-[10px] tabular-nums',
            isDanger
              ? 'text-red-400'
              : isWarn
                ? 'text-amber-400'
                : 'text-(--color-text-muted)',
          )}
        >
          {pct}%
        </span>
      )}
    </div>
  )
}
