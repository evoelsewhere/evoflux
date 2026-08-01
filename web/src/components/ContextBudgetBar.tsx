/**
 * ContextBudgetBar — compact token-usage control for the workbench topbar.
 *
 * Trigger: thin meter + percent. Click opens a Cursor-style "Context Usage"
 * popover: summary row, segmented bar, and color-swatch breakdown.
 *
 * Categories map to real AgentUsage fields only (input / cache / output) —
 * no invented system-prompt / rules / skills slices without backend data.
 */

import { useState } from 'react'
import { X } from 'lucide-react'
import {
  Popover,
  PopoverClose,
  PopoverContent,
  PopoverTitle,
  PopoverTrigger,
} from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import { formatTokens as formatTokensShort } from '@/utils/format'

/** Fallback when the model catalog has no context_length. */
const DEFAULT_CONTEXT_MAX = 200_000

export interface ContextBudgetBarProps {
  /** Tokens currently occupying the context window (typically last prompt). */
  used: number
  /** Context window ceiling; defaults to 200 000. */
  max?: number
  className?: string
  /** Show the percentage label on the trigger. Defaults to true. */
  showLabel?: boolean
  /** Compact trigger for dense chrome. */
  compact?: boolean
  /** Latest input-token count (prompt). */
  input?: number
  /** Cumulative output-token count. */
  output?: number
  /** Latest cache-token count. */
  cached?: number
  /** Auto-summary input threshold. */
  trigger?: number
}

type UsageCategoryId = 'input' | 'cache' | 'output'

interface UsageCategory {
  id: UsageCategoryId
  label: string
  tokens: number
  /** CSS color token used for swatch + bar segment. */
  color: string
  /** When true, segment contributes to the context-window fill bar. */
  inContext: boolean
}

function formatTokenCount(n: number): string {
  if (n >= 1_000_000) {
    const v = n / 1_000_000
    return `${v >= 10 ? v.toFixed(0) : v.toFixed(1).replace(/\.0$/, '')}M`
  }
  if (n >= 1_000) {
    const v = n / 1_000
    return `${v >= 100 ? v.toFixed(0) : v.toFixed(1).replace(/\.0$/, '')}K`
  }
  return String(Math.round(n))
}

function buildCategories(input: number, cached: number, output: number): UsageCategory[] {
  const safeCache = Math.max(0, Math.min(cached, Math.max(input, 0)))
  const freshInput = Math.max(0, input - safeCache)
  // Input + cache partition the current context window. Output is session
  // cumulative and is listed for transparency but is not a context slice
  // (prompt already includes prior turns).
  return [
    {
      id: 'input',
      label: 'Input',
      tokens: freshInput,
      color: 'var(--accent-blue)',
      inContext: true,
    },
    {
      id: 'cache',
      label: 'Cache',
      tokens: safeCache,
      color: 'var(--accent-purple)',
      inContext: true,
    },
    {
      id: 'output',
      label: 'Output',
      tokens: Math.max(0, output),
      color: 'var(--accent-orange)',
      inContext: false,
    },
  ]
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
  const [open, setOpen] = useState(false)
  const safeMax = Math.max(max, 1)
  // Context occupancy is the latest prompt size; fall back to `used` when
  // callers only pass a single aggregate.
  const contextUsed = Math.max(input > 0 ? input : used, 0)
  const pct = Math.min(100, Math.round((contextUsed / safeMax) * 100))
  const isDanger = pct >= 95
  const isWarn = pct >= 80 || (trigger !== undefined && contextUsed >= trigger)
  const categories = buildCategories(input > 0 ? input : used, cached, output)
  const contextCategories = categories.filter((c) => c.inContext && c.tokens > 0)
  const contextSegmentTotal = contextCategories.reduce((sum, c) => sum + c.tokens, 0)
  const summaryUsed = contextSegmentTotal > 0 ? contextSegmentTotal : contextUsed

  const ariaLabel = isDanger
    ? `Context ${pct}% full — auto-summarization imminent (${formatTokensShort(contextUsed)} / ${formatTokensShort(safeMax)})`
    : isWarn
      ? `Context ${pct}% full — summarization may trigger soon (${formatTokensShort(contextUsed)} / ${formatTokensShort(safeMax)})`
      : `Context ${pct}% used (${formatTokensShort(contextUsed)} / ${formatTokensShort(safeMax)})`

  const triggerMeter = (
    <span
      className={cn(
        'group relative flex items-center outline-none',
        compact ? 'gap-1 px-1.5' : 'h-8 gap-1.5 rounded-md px-2',
        className,
      )}
    >
      <span
        className={cn(
          'relative flex overflow-hidden rounded-full bg-(--color-border-subtle)',
          compact ? 'h-1.5 w-10' : 'h-1.5 w-14',
        )}
        aria-hidden="true"
      >
        {contextCategories.length > 0 ? (
          contextCategories.map((cat) => (
            <span
              key={cat.id}
              className="h-full min-w-px"
              style={{
                width: `${(cat.tokens / Math.max(summaryUsed, 1)) * pct}%`,
                backgroundColor: cat.color,
              }}
            />
          ))
        ) : (
          <span
            className={cn(
              'h-full rounded-full transition-[width] duration-(--motion-glacial)',
              isDanger ? 'bg-(--color-error)' : isWarn ? 'bg-(--color-warning)' : 'bg-(--accent-blue)',
            )}
            style={{ width: `${pct}%` }}
          />
        )}
      </span>
      {showLabel && (
        <span
          className={cn(
            'font-mono text-[10px] tabular-nums',
            isDanger
              ? 'text-(--color-error)'
              : isWarn
                ? 'text-(--color-warning)'
                : 'text-(--color-text-muted)',
          )}
        >
          {pct}%
        </span>
      )}
    </span>
  )

  // Hide until there is something useful to show.
  const hasAnyTokens = categories.some((c) => c.tokens > 0) || contextUsed > 0
  if (!hasAnyTokens) {
    return null
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <button
            type="button"
            aria-label={ariaLabel}
            aria-haspopup="dialog"
            className={cn(
              'rounded-lg outline-none transition-colors',
              'hover:bg-(--bg-key) focus-visible:ring-2 focus-visible:ring-(--focus-ring)',
              open && 'bg-(--bg-key)',
            )}
          />
        }
      >
        {triggerMeter}
      </PopoverTrigger>

      <PopoverContent
        align="end"
        sideOffset={8}
        className="w-[min(17.5rem,calc(100vw-1.5rem))] gap-0 rounded-[10px] border-(--color-border) bg-(--bg-card) p-3.5 shadow-(--shadow-popover)"
      >
        {/* Header */}
        <div className="mb-3 flex items-center justify-between gap-3">
          <PopoverTitle className="text-[13px] font-medium leading-none text-(--color-text)">
            Context Usage
          </PopoverTitle>
          <PopoverClose
            render={
              <button
                type="button"
                aria-label="Close context usage"
                className="flex size-6 items-center justify-center rounded-md text-(--color-text-muted) outline-none transition-colors hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:ring-2 focus-visible:ring-(--focus-ring)"
              />
            }
          >
            <X size={14} strokeWidth={1.75} aria-hidden="true" />
          </PopoverClose>
        </div>

        {/* Summary */}
        <div className="mb-2.5 flex items-baseline justify-between gap-3 text-[12px] leading-none">
          <span className="font-medium tabular-nums text-(--color-text)">{pct}% Full</span>
          <span className="tabular-nums text-(--color-text-muted)">
            ~{formatTokenCount(summaryUsed)} / {formatTokenCount(safeMax)} Tokens
          </span>
        </div>

        {/* Segmented progress bar — filled share = % Full; slices = context categories */}
        <div
          className="mb-3.5 flex h-1.5 w-full gap-px overflow-hidden rounded-full bg-(--bg-key)"
          role="meter"
          aria-valuemin={0}
          aria-valuemax={safeMax}
          aria-valuenow={Math.min(contextUsed, safeMax)}
          aria-label={ariaLabel}
        >
          {contextCategories.map((cat) => {
            const shareOfUsed = cat.tokens / Math.max(summaryUsed, 1)
            const widthPct = Math.max(0.35, shareOfUsed * pct)
            return (
              <span
                key={cat.id}
                title={`${cat.label}: ${formatTokenCount(cat.tokens)}`}
                className="h-full min-w-px first:rounded-l-full last:rounded-r-full"
                style={{
                  width: `${widthPct}%`,
                  backgroundColor: cat.color,
                }}
              />
            )
          })}
        </div>

        {/* Breakdown */}
        <ul className="flex flex-col gap-2" aria-label="Token usage breakdown">
          {categories
            .filter((cat) => cat.tokens > 0)
            .map((cat) => (
              <li
                key={cat.id}
                className="flex items-center justify-between gap-3 text-[12px] leading-none"
              >
                <span className="flex min-w-0 items-center gap-2 text-(--color-text-2)">
                  <span
                    className="size-2.5 shrink-0 rounded-[3px]"
                    style={{ backgroundColor: cat.color }}
                    aria-hidden="true"
                  />
                  <span className="truncate">{cat.label}</span>
                </span>
                <span className="shrink-0 tabular-nums text-(--color-text-muted)">
                  {formatTokenCount(cat.tokens)}
                </span>
              </li>
            ))}
          {trigger !== undefined && trigger > 0 && (
            <li className="mt-1 flex items-center justify-between gap-3 border-t border-(--color-border) pt-2.5 text-[11px] leading-none text-(--color-text-subtle)">
              <span>Auto-summary at</span>
              <span className="tabular-nums">{formatTokenCount(trigger)}</span>
            </li>
          )}
        </ul>
      </PopoverContent>
    </Popover>
  )
}
