/**
 * ContextBudgetBar — compact token-usage bar for the chat topbar.
 *
 * Shows:  [████████░░░] 68%  with color transitions at 80% and 95%.
 * Hovering or focusing the bar reveals the full input/output/cache breakdown.
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
  /** Compact mode for embedding in ViewModeSwitch. */
  compact?: boolean
  /** Latest input-token count shown in the detail tooltip. */
  input?: number
  /** Cumulative output-token count shown in the detail tooltip. */
  output?: number
  /** Latest cache-token count shown in the detail tooltip. */
  cached?: number
  /** Auto-summary input threshold shown in the detail tooltip. */
  trigger?: number
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
  compact = false,
  input = 0,
  output = 0,
  cached = 0,
  trigger,
}: ContextBudgetBarProps) {
  const safeMax = Math.max(max, 1)
  const pct = Math.min(100, Math.round((used / safeMax) * 100))
  const isDanger = pct >= 95
  const isWarn = pct >= 80

  const barColor = isDanger
    ? 'bg-red-500'
    : isWarn
      ? 'bg-amber-400'
      : 'bg-(--accent-blue)'

  const tooltip = isDanger
    ? `Context ${pct}% full — auto-summarization imminent (${formatTokens(used)} / ${formatTokens(safeMax)})`
    : isWarn
      ? `Context ${pct}% full — summarization may trigger soon (${formatTokens(used)} / ${formatTokens(safeMax)})`
      : `Context ${pct}% used (${formatTokens(used)} / ${formatTokens(safeMax)})`

  const detailTooltip = (
    <div
      className="pointer-events-none invisible absolute right-0 top-full z-(--z-modal) mt-2 min-w-48 rounded-lg border border-(--color-border) bg-(--bg-page)/95 px-3 py-2.5 font-mono text-xs leading-5 text-(--color-text) opacity-0 shadow-xl backdrop-blur-xl transition-[opacity,visibility] group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100"
      role="tooltip"
    >
      <div className="flex justify-between gap-5"><span className="text-(--color-text-muted)">input</span><span>{input.toLocaleString()}</span></div>
      {trigger !== undefined && (
        <div className="flex justify-between gap-5"><span className="text-(--color-text-muted)">trigger</span><span>{trigger.toLocaleString()}</span></div>
      )}
      <div className="flex justify-between gap-5"><span className="text-(--color-text-muted)">used</span><span>{pct}%</span></div>
      <div className="flex justify-between gap-5"><span className="text-(--color-text-muted)">output</span><span>{output.toLocaleString()}</span></div>
      <div className="flex justify-between gap-5"><span className="text-(--color-text-muted)">cache</span><span>{cached.toLocaleString()}</span></div>
    </div>
  )

  if (compact) {
    return (
      <div
        className={cn('group relative flex items-center gap-1 px-2 outline-none', className)}
        role="meter"
        tabIndex={0}
        aria-valuemin={0}
        aria-valuemax={safeMax}
        aria-valuenow={Math.min(used, safeMax)}
        aria-label={tooltip}
      >
        <div className="relative h-1.5 w-10 overflow-hidden rounded-full bg-(--border-subtle)">
          <div
            className={cn('absolute inset-y-0 left-0 rounded-full transition-all duration-700', barColor)}
            style={{ width: `${pct}%` }}
          />
        </div>
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
        {detailTooltip}
      </div>
    )
  }

  return (
    <div
      className={cn('group relative inline-flex h-8 items-center gap-1.5 rounded-md px-2 outline-none', className)}
      role="meter"
      tabIndex={0}
      aria-valuemin={0}
      aria-valuemax={safeMax}
      aria-valuenow={Math.min(used, safeMax)}
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
      {detailTooltip}
    </div>
  )
}
