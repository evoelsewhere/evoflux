/**
 * ContextBudgetBar — compact token-usage control for the workbench topbar.
 *
 * Trigger: thin meter + percent. Click opens a Cursor-style "Context Usage"
 * popover: summary row, segmented bar, and color-swatch breakdown.
 *
 * Current context is the latest main prompt. Turn usage is a separate total
 * across primary and auxiliary model calls.
 */

import { useState } from 'react'
import { LoaderCircle, Minimize2, X } from 'lucide-react'
import type { ContextSettings, TurnCost } from '@/api/types'
import {
  useContextSettingsQuery,
  useUpdateContextSettingsMutation,
} from '@/queries'
import { costTooltip, formatTurnCost } from '@/utils/turn-meta'
import {
  Popover,
  PopoverClose,
  PopoverContent,
  PopoverTitle,
  PopoverTrigger,
} from '@/components/ui/popover'
import { SelectControl } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { formatTokens as formatTokensShort } from '@/utils/format'

/** Fallback when the model catalog has no context_length. */
const DEFAULT_CONTEXT_MAX = 200_000

export interface ContextBudgetBarProps {
  /** Tokens currently occupying the context window (typically last prompt). */
  used: number
  /** Context window ceiling; defaults to 200 000. */
  max?: number
  /**
   * The model's real context window, or `undefined` when it is not in the
   * registry. Unlike `max` this is never defaulted, so it is what the
   * threshold list uses to say which choices this model cannot reach.
   */
  contextLength?: number
  className?: string
  /** Show the percentage label on the trigger. Defaults to true. */
  showLabel?: boolean
  /** Compact trigger for dense chrome. */
  compact?: boolean
  /** Latest input-token count (prompt) — includes cache reads and writes. */
  input?: number
  /** Latest cache-read token count. Subset of `input`. */
  cached?: number
  /** Latest cache-write token count. Subset of `input`, billed at ~1.25x. */
  cacheWrite?: number
  /** Total input tokens consumed by all model calls in the current turn. */
  turnInput?: number
  /** Total output tokens consumed by all model calls in the current turn. */
  turnOutput?: number
  /** Total cache-read tokens this turn. Subset of `turnInput`. */
  turnCached?: number
  /** Total cache-write tokens this turn. Subset of `turnInput`. */
  turnCacheWrite?: number
  /** Number of model calls included in the current turn total. */
  turnCalls?: number
  /** What this turn cost, by component, priced from the models.dev catalog. */
  cost?: TurnCost
  /** Auto-summary input threshold, already clamped to the model's window. */
  trigger?: number
  /** Manually summarize earlier turns to free context. */
  onCompact?: () => void | Promise<void>
  /** Disable manual compaction while the session is busy. */
  compactDisabled?: boolean
}

type UsageCategoryId = 'input' | 'cache' | 'cacheWrite' | 'output'

interface UsageCategory {
  id: UsageCategoryId
  label: string
  tokens: number
  /** CSS color token used for swatch + bar segment. */
  color: string
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

/**
 * Split a prompt total into the three classes the provider bills separately.
 *
 * `input` from the API is the whole prompt: cache reads (~0.1x) and cache
 * writes (~1.25x) are already inside it. Subtracting both leaves the tokens
 * charged at the plain rate, so the three slices partition the prompt
 * exactly and can be read as a sum.
 */
function buildContextCategories(
  input: number,
  cached: number,
  cacheWrite = 0,
): UsageCategory[] {
  const total = Math.max(input, 0)
  const safeCache = Math.max(0, Math.min(cached, total))
  const safeWrite = Math.max(0, Math.min(cacheWrite, total - safeCache))
  const freshInput = Math.max(0, total - safeCache - safeWrite)
  return [
    {
      id: 'input',
      label: 'Fresh input',
      tokens: freshInput,
      color: 'var(--accent-blue)',
    },
    {
      id: 'cache',
      label: 'Cache read',
      tokens: safeCache,
      color: 'var(--accent-purple)',
    },
    {
      id: 'cacheWrite',
      label: 'Cache write',
      tokens: safeWrite,
      color: 'var(--accent-orange)',
    },
  ]
}

/**
 * Share of a prompt the provider served from its cache.
 *
 * Returns `null` when there is no cache signal at all — a provider that never
 * reports cache reads is indistinguishable from one that reported zero, and
 * printing "0% cached" for the former reads as a regression that isn't there.
 */
function cacheHitPercent(
  input: number,
  cached: number,
  cacheWrite = 0,
): number | null {
  if (input <= 0) return null
  if (cached <= 0 && cacheWrite <= 0) return null
  return Math.min(100, Math.round((Math.max(cached, 0) / input) * 100))
}

/**
 * One block of token accounting: a ratio bar, then the rows that add up to it.
 *
 * The bar carries the colour coding, so a row's dot reads as "this slice"
 * rather than as decoration, and the two blocks in the popover stay visually
 * parallel instead of each inventing its own layout.
 */
function UsageSection({
  id,
  title,
  meta,
  cacheHit,
  categories,
  footer,
  divided = false,
}: {
  id: string
  title: string
  meta?: string
  cacheHit: number | null
  categories: UsageCategory[]
  footer?: React.ReactNode
  /** Draw a rule above this block, separating it from the one before. */
  divided?: boolean
}) {
  const rows = categories.filter((category) => category.tokens > 0)
  if (rows.length === 0) return null
  const total = rows.reduce((sum, row) => sum + row.tokens, 0)

  return (
    <section
      className={cn(
        'mt-3 border-(--color-border) pt-3',
        divided ? 'border-t' : 'mt-0 pt-0',
      )}
      aria-labelledby={`${id}-heading`}
    >
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <h3
          id={`${id}-heading`}
          className="flex min-w-0 items-baseline gap-1.5 text-[11px] font-medium text-(--color-text-2)"
        >
          <span className="truncate">{title}</span>
          {meta && (
            <span className="shrink-0 text-[10px] font-normal text-(--color-text-subtle)">
              {meta}
            </span>
          )}
        </h3>
        {cacheHit !== null && (
          <span
            className="shrink-0 text-[11px] font-medium tabular-nums text-(--accent-purple)"
            title="Share of these input tokens the provider served from its cache"
          >
            {cacheHit}% cached
          </span>
        )}
      </div>
      <div
        className="mb-2 flex h-1 w-full gap-px overflow-hidden rounded-full bg-(--bg-key)"
        aria-hidden="true"
      >
        {rows.map((row) => (
          <span
            key={row.id}
            className="h-full min-w-px first:rounded-l-full last:rounded-r-full"
            style={{
              width: `${(row.tokens / Math.max(total, 1)) * 100}%`,
              backgroundColor: row.color,
            }}
          />
        ))}
      </div>
      <ul className="flex flex-col gap-1.5" aria-label={`${title} breakdown`}>
        {rows.map((row) => (
          <li
            key={row.id}
            className="flex items-center justify-between gap-3 text-[12px] leading-none"
          >
            <span className="flex min-w-0 items-center gap-2 text-(--color-text-2)">
              <span
                className="size-2 shrink-0 rounded-full"
                style={{ backgroundColor: row.color }}
                aria-hidden="true"
              />
              <span className="truncate">{row.label}</span>
            </span>
            <span className="shrink-0 tabular-nums text-(--color-text-muted)">
              {formatTokenCount(row.tokens)}
            </span>
          </li>
        ))}
      </ul>
      {footer && (
        <div className="mt-2 border-t border-(--color-border) pt-2">{footer}</div>
      )}
    </section>
  )
}

/**
 * Selectable thresholds, bracketing the cost-optimal value so the trade-off
 * is visible in both directions: lower compacts sooner and spends less on
 * carried context, higher keeps more history verbatim.
 */
const THRESHOLD_PRESETS = [60_000, 100_000, 150_000, 250_000, 350_000, 500_000, 750_000]

/**
 * Highest threshold the model in front of the user can actually reach. The
 * setting is global, so a choice above this is still legitimate — it simply
 * has no effect here, and every option says so rather than silently
 * disappearing from a list that other models still need.
 */
function modelCeiling(
  settings: ContextSettings,
  contextLength: number | undefined,
): number | null {
  // Undefined means the model is not in the registry, so nothing is known
  // about its window — say nothing rather than guess from the bar's
  // placeholder scale.
  if (!contextLength || !(settings.context_ratio > 0)) return null
  return Math.min(settings.max_tokens, Math.floor(contextLength * settings.context_ratio))
}

function thresholdOptions(settings: ContextSettings, contextLength: number | undefined) {
  const ceiling = modelCeiling(settings, contextLength)
  const label = (value: number, base: string) =>
    ceiling !== null && value > ceiling
      ? `${base} (${formatTokenCount(ceiling)} here)`
      : base
  return [
    {
      value: 'default',
      label: label(
        settings.defaults.summary_trigger_tokens,
        `Cost-optimal — ${formatTokenCount(settings.defaults.summary_trigger_tokens)}`,
      ),
    },
    ...THRESHOLD_PRESETS.filter((value) => value <= settings.max_tokens).map(
      (value) => ({
        value: String(value),
        label: label(value, formatTokenCount(value)),
      }),
    ),
  ]
}

export function ContextBudgetBar({
  used,
  max = DEFAULT_CONTEXT_MAX,
  contextLength,
  className,
  showLabel = true,
  compact = false,
  input = 0,
  cached = 0,
  cacheWrite = 0,
  turnInput,
  turnOutput,
  turnCached,
  turnCacheWrite,
  turnCalls,
  cost,
  trigger,
  onCompact,
  compactDisabled = false,
}: ContextBudgetBarProps) {
  const [open, setOpen] = useState(false)
  const [compactPending, setCompactPending] = useState(false)
  // Auto-compaction is a global setting shared with the Context settings
  // page. Going through the same query keeps the two in step and, on save,
  // refreshes the per-model trigger this popover prints beside it.
  const contextSettings = useContextSettingsQuery(open).data ?? null
  const updateThreshold = useUpdateContextSettingsMutation()
  const safeMax = Math.max(max, 1)
  // Context occupancy is the latest prompt size; fall back to `used` when
  // callers only pass a single aggregate.
  const contextUsed = Math.max(input > 0 ? input : used, 0)
  const pct = Math.min(100, Math.round((contextUsed / safeMax) * 100))
  const isDanger = pct >= 95
  const isWarn = pct >= 80 || (trigger !== undefined && contextUsed >= trigger)
  const contextCategories = buildContextCategories(
    input > 0 ? input : used,
    cached,
    cacheWrite,
  ).filter((category) => category.tokens > 0)
  const contextSegmentTotal = contextCategories.reduce((sum, c) => sum + c.tokens, 0)
  const summaryUsed = contextSegmentTotal > 0 ? contextSegmentTotal : contextUsed
  const safeTurnInput = Math.max(turnInput ?? 0, 0)
  const safeTurnOutput = Math.max(turnOutput ?? 0, 0)
  // The turn's input is one total that already contains its cache reads and
  // writes. Partition it the same way as the context breakdown above, so the
  // rows can be added up instead of double-counting the cached share.
  const turnCategories = buildContextCategories(
    safeTurnInput,
    turnCached ?? 0,
    turnCacheWrite ?? 0,
  )
  const hasTurnUsage = safeTurnInput > 0 || safeTurnOutput > 0
  const contextCacheHit = cacheHitPercent(
    input > 0 ? input : used,
    cached,
    cacheWrite,
  )
  const turnCacheHit = cacheHitPercent(
    safeTurnInput,
    turnCached ?? 0,
    turnCacheWrite ?? 0,
  )
  // Where auto-compaction sits on the window bar, when it is inside it.
  const compactMarkerPct =
    trigger !== undefined && trigger > 0 && trigger < safeMax
      ? Math.min(99, (trigger / safeMax) * 100)
      : null

  const handleThresholdChange = (raw: string) => {
    updateThreshold.mutate({
      summary_trigger_tokens: raw === 'default' ? null : Number(raw),
    })
  }

  const handleCompact = async () => {
    if (!onCompact || compactDisabled || compactPending) return
    setCompactPending(true)
    try {
      await onCompact()
    } catch {
      // The action owner surfaces command errors; keep this control retryable.
    } finally {
      setCompactPending(false)
    }
  }

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
  const hasAnyTokens = contextCategories.length > 0 || contextUsed > 0 || hasTurnUsage
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
        side="bottom"
        sideOffset={8}
        collisionPadding={12}
        className="w-[min(19rem,calc(100vw-1.5rem))] gap-0 rounded-[10px] border-(--color-border) bg-(--bg-card) p-3.5 shadow-(--shadow-popover)"
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

        {/* How full the window is — one bar, one number, and where
            auto-compaction sits on it. */}
        <section className="mb-4" aria-labelledby="window-heading">
          <div className="mb-1.5 flex items-baseline justify-between gap-3">
            <h3
              id="window-heading"
              className="text-[12px] font-medium leading-none text-(--color-text)"
            >
              {formatTokenCount(summaryUsed)} in context
            </h3>
            <span className="text-[11px] tabular-nums leading-none text-(--color-text-muted)">
              {pct}% of {formatTokenCount(safeMax)}
            </span>
          </div>
          <div
            className="relative h-1.5 w-full overflow-hidden rounded-full bg-(--bg-key)"
            role="meter"
            aria-valuemin={0}
            aria-valuemax={safeMax}
            aria-valuenow={Math.min(contextUsed, safeMax)}
            aria-label={ariaLabel}
          >
            <span
              className={cn(
                'absolute inset-y-0 left-0 rounded-full transition-[width] duration-(--motion-glacial)',
                isDanger
                  ? 'bg-(--color-error)'
                  : isWarn
                    ? 'bg-(--color-warning)'
                    : 'bg-(--accent-blue)',
              )}
              style={{ width: `${Math.max(pct, 1)}%` }}
            />
            {compactMarkerPct !== null && (
              // The threshold is a place on this bar, so draw it there instead
              // of spending another text row on the number.
              <span
                className="absolute inset-y-0 w-px bg-(--color-text-subtle)"
                style={{ left: `${compactMarkerPct}%` }}
                aria-hidden="true"
              />
            )}
          </div>
          {trigger !== undefined && trigger > 0 && (
            <p className="mt-1.5 text-[10px] leading-none text-(--color-text-subtle)">
              Auto-compacts at {formatTokenCount(trigger)}
            </p>
          )}
        </section>

        <UsageSection
          id="latest-prompt"
          title="Latest prompt"
          cacheHit={contextCacheHit}
          categories={contextCategories}
        />

        {hasTurnUsage && (
          <UsageSection
            divided
            id="this-turn"
            title="This turn"
            meta={
              turnCalls
                ? `${turnCalls} model ${turnCalls === 1 ? 'call' : 'calls'}`
                : 'all model calls'
            }
            cacheHit={turnCacheHit}
            categories={[
              ...turnCategories.filter((category) => category.tokens > 0),
              {
                id: 'output',
                label: 'Output',
                tokens: safeTurnOutput,
                color: 'var(--accent-green)',
              } satisfies UsageCategory,
            ]}
            footer={
              cost && cost.estimated_usd > 0 ? (
                <div
                  className="flex items-center justify-between gap-3 text-[12px] leading-none"
                  title={costTooltip(cost)}
                >
                  <span className="text-(--color-text-2)">Cost</span>
                  <span className="font-medium tabular-nums text-(--color-text)">
                    {formatTurnCost(cost.estimated_usd)}
                  </span>
                </div>
              ) : undefined
            }
          />
        )}

        {/* A control, not a statistic — so it sits below the numbers. */}
        <section
          className="mt-4 border-t border-(--color-border) pt-3"
          aria-labelledby="auto-compact-heading"
        >
          <h3
            id="auto-compact-heading"
            className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-(--color-text-subtle)"
          >
            Compaction threshold
          </h3>
          {contextSettings ? (
            <>
              <SelectControl
                size="sm"
                value={String(contextSettings.summary_trigger_tokens ?? 'default')}
                disabled={updateThreshold.isPending}
                onValueChange={handleThresholdChange}
                ariaLabel="Auto-compaction threshold"
                options={thresholdOptions(contextSettings, contextLength)}
              />
              <p className="mt-1.5 text-[10px] leading-snug text-(--color-text-subtle)">
                {contextSettings.summary_trigger_tokens === null
                  ? 'Lower compacts sooner and carries fewer tokens; each compaction loses some detail.'
                  : 'Global override, clamped to 75% of each model’s window.'}
              </p>
            </>
          ) : (
            <p className="text-[10px] text-(--color-text-subtle)">Loading…</p>
          )}
        </section>

        {onCompact && (
          <div className="mt-3 border-t border-(--color-border) pt-3">
            <button
              type="button"
              onClick={() => void handleCompact()}
              disabled={compactDisabled || compactPending}
              aria-label={compactPending ? 'Compacting context' : 'Compact context'}
              title={compactDisabled ? 'Wait for the current turn to finish' : undefined}
              className="flex h-8 w-full items-center justify-center gap-2 rounded-lg border border-(--color-border) bg-(--bg-key) px-3 text-[12px] font-medium text-(--color-text-2) outline-none transition-colors hover:border-(--color-border-strong) hover:bg-(--bg-hover) hover:text-(--color-text) focus-visible:ring-2 focus-visible:ring-(--focus-ring) disabled:cursor-not-allowed disabled:opacity-50"
            >
              {compactPending ? (
                <LoaderCircle size={13} className="animate-spin" aria-hidden="true" />
              ) : (
                <Minimize2 size={13} aria-hidden="true" />
              )}
              <span>{compactPending ? 'Compacting…' : 'Compact context'}</span>
            </button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}
