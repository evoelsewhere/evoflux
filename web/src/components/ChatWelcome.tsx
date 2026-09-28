import { useState } from 'react'
import { motion } from 'framer-motion'
import { MessageSquareText, Paperclip } from 'lucide-react'

import EvoFluxLogo from '@/assets/brand/evoflux-app-icon.png'
import type { ObservabilitySummary } from '@/api/client'
import { fadeRise, useMotionPreset } from '@/lib/motion'
import { useObservabilitySummaryQuery } from '@/queries'
import { useI18n } from '@/i18n'
import { cn } from '@/lib/utils'
import { formatCompact, formatInt } from '@/utils/telemetryFormat'

interface ChatWelcomeProps {
  context?: React.ReactNode
}

type UsageView = 'overview' | 'models'
type UsagePeriod = 'all' | 30 | 7

const DAY_MS = 86_400_000
const HEATMAP_WEEKS = 26

interface HeatmapDay {
  day: string
  turns: number
  future: boolean
}

function totalTokens(input: number, output: number): string {
  return formatCompact(input + output)
}

function isoDay(date: Date): string {
  return date.toISOString().slice(0, 10)
}

function utcToday(): Date {
  const now = new Date()
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()))
}

function activityDays(data: ObservabilitySummary): Set<string> {
  return new Set(data.daily_turns.filter((day) => day.turns > 0).map((day) => day.day))
}

function streaks(data: ObservabilitySummary, queryDays: number): { current: number; longest: number } {
  const active = activityDays(data)
  const today = utcToday()
  let current = 0

  for (let offset = 0; offset < queryDays; offset += 1) {
    const day = isoDay(new Date(today.getTime() - offset * DAY_MS))
    if (!active.has(day)) break
    current += 1
  }

  let running = 0
  let longest = 0
  for (let offset = queryDays - 1; offset >= 0; offset -= 1) {
    const day = isoDay(new Date(today.getTime() - offset * DAY_MS))
    if (active.has(day)) {
      running += 1
      longest = Math.max(longest, running)
    } else {
      running = 0
    }
  }

  return { current, longest }
}

function buildHeatmap(data: ObservabilitySummary): HeatmapDay[] {
  const turnsByDay = new Map(data.daily_turns.map((day) => [day.day, day.turns]))
  const today = utcToday()
  const weekEnd = new Date(today)
  weekEnd.setUTCDate(weekEnd.getUTCDate() + (6 - weekEnd.getUTCDay()))
  const firstDay = new Date(weekEnd.getTime() - (HEATMAP_WEEKS * 7 - 1) * DAY_MS)

  return Array.from({ length: HEATMAP_WEEKS * 7 }, (_, index) => {
    const date = new Date(firstDay.getTime() + index * DAY_MS)
    const day = isoDay(date)
    return {
      day,
      turns: turnsByDay.get(day) ?? 0,
      future: date.getTime() > today.getTime(),
    }
  })
}

function heatLevel(turns: number, maxTurns: number): number {
  if (turns <= 0) return 0
  const ratio = turns / maxTurns
  if (ratio <= 0.25) return 1
  if (ratio <= 0.5) return 2
  if (ratio <= 0.75) return 3
  return 4
}

/**
 * The empty-state welcome shared by Work and Coding: a centered greeting
 * (icon, title, one line of guidance, then actions or hints) over a light
 * usage summary. It used to be a split card of boxed tiles in 10px bold type,
 * which read as dense and heavy for a screen whose job is to invite a start.
 */
export function WelcomeHero({
  icon,
  title,
  description,
  children,
}: {
  icon: React.ReactNode
  title: string
  description: string
  /** Actions (a primary button) or hint chips under the description. */
  children?: React.ReactNode
}) {
  const preset = useMotionPreset()
  const enter = fadeRise(preset, 12)

  return (
    <motion.div
      initial={enter.initial}
      animate={enter.animate}
      transition={enter.transition}
      className="mx-auto flex w-full max-w-[34rem] flex-col items-center text-center"
    >
      <div className="flex size-11 items-center justify-center rounded-2xl bg-(--color-accent)/10 text-(--color-accent)">
        {icon}
      </div>
      <h2 className="mt-4 text-lg font-medium tracking-tight text-balance text-(--color-text)">
        {title}
      </h2>
      <p className="mt-1.5 max-w-[26rem] text-sm leading-relaxed text-pretty text-(--color-text-muted)">
        {description}
      </p>
      {children && (
        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">{children}</div>
      )}
      <RecentUsageCard className="mt-8" />
    </motion.div>
  )
}

/** A quiet suggestion chip for the welcome's hint row. */
export function WelcomeHint({ icon: Icon, label }: { icon: typeof Paperclip; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-(--color-border-subtle) px-3 py-1 text-xs text-(--color-text-2)">
      <Icon size={13} className="text-(--color-text-muted)" aria-hidden="true" />
      {label}
    </span>
  )
}

export function ChatWelcome({ context }: ChatWelcomeProps) {
  return (
    <WelcomeHero
      icon={
        <img
          src={EvoFluxLogo}
          className="size-7 rounded-lg"
          width={28}
          height={28}
          alt=""
          aria-hidden="true"
        />
      }
      title="What would you like to accomplish?"
      description="Start with the outcome. EvoFlux will plan the work and carry the task through."
    >
      <WelcomeHint icon={MessageSquareText} label="Describe the outcome" />
      <WelcomeHint icon={Paperclip} label="Add useful context" />
      {context && <div className="w-full">{context}</div>}
    </WelcomeHero>
  )
}

export function RecentUsageCard({ className }: { className?: string }) {
  const [view, setView] = useState<UsageView>('overview')
  const [period, setPeriod] = useState<UsagePeriod>('all')
  const queryDays = period === 'all' ? 90 : period
  const summary = useObservabilitySummaryQuery(queryDays)

  return (
    <section
      className={cn(
        '@container/usage w-full rounded-2xl border border-(--color-border-subtle) bg-(--bg-card)/60 p-4 text-left',
        className,
      )}
      aria-label="Recent usage"
    >
      <div className="flex items-center justify-between gap-3">
        <Segmented
          role="tablist"
          ariaLabel="Usage view"
          options={[['overview', 'Overview'], ['models', 'Models']] as const}
          value={view}
          onChange={setView}
        />
        <Segmented
          ariaLabel="Usage period"
          options={[['all', 'All'], [30, '30d'], [7, '7d']] as const}
          value={period}
          onChange={setPeriod}
        />
      </div>

      {summary.isLoading ? (
        <div className="mt-4 space-y-4" aria-hidden="true">
          <div className="grid grid-cols-2 gap-x-4 gap-y-3 @[26rem]/usage:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index}>
                <div className="skeleton-shimmer h-2.5 w-12 rounded" />
                <div className="skeleton-shimmer mt-1.5 h-4 w-10 rounded" />
              </div>
            ))}
          </div>
          <div className="skeleton-shimmer h-[5.25rem] rounded-md" />
        </div>
      ) : summary.isError || !summary.data ? (
        <p className="py-8 text-center text-xs text-(--color-text-subtle)">
          Usage data is unavailable.
        </p>
      ) : view === 'overview' ? (
        <UsageOverview data={summary.data} queryDays={queryDays} />
      ) : (
        <ModelUsage data={summary.data} />
      )}
    </section>
  )
}

/** Small text segmented control for the usage card's view and period. */
function Segmented<T extends string | number>({
  role,
  ariaLabel,
  options,
  value,
  onChange,
}: {
  role?: 'tablist'
  ariaLabel: string
  options: ReadonlyArray<readonly [T, string]>
  value: T
  onChange: (value: T) => void
}) {
  return (
    <div
      role={role}
      aria-label={ariaLabel}
      className="flex items-center gap-0.5 rounded-lg bg-(--color-text)/4 p-0.5"
    >
      {options.map(([option, label]) => {
        const selected = option === value
        return (
          <button
            key={String(option)}
            type="button"
            {...(role === 'tablist' ? { role: 'tab', 'aria-selected': selected } : { 'aria-pressed': selected })}
            onClick={() => onChange(option)}
            className={cn(
              'rounded-md px-2 py-0.5 text-xs transition-colors',
              selected
                ? 'bg-(--bg-card) text-(--color-text) shadow-xs'
                : 'text-(--color-text-muted) hover:text-(--color-text)',
            )}
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}

function UsageOverview({ data, queryDays }: { data: ObservabilitySummary; queryDays: number }) {
  const { intlLocale } = useI18n()
  const activeDayCount = activityDays(data).size
  const { current, longest } = streaks(data, queryDays)
  const favoriteModel = [...data.by_model].sort((a, b) => b.calls - a.calls)[0]?.model ?? '—'
  const peakDay = [...data.daily_turns].sort((a, b) => b.turns - a.turns)[0]
  const peakDayLabel = peakDay
    ? new Intl.DateTimeFormat(intlLocale, { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(
        new Date(`${peakDay.day}T00:00:00Z`),
      )
    : '—'
  const tokens = totalTokens(data.totals.input_tokens, data.totals.output_tokens)
  // Four headline numbers; the rest read as one quiet line underneath
  // instead of eight equal boxes competing for attention.
  const stats = [
    ['Turns', formatInt(data.totals.turns)],
    ['Total tokens', tokens],
    ['Active days', formatInt(activeDayCount)],
    ['Current streak', `${current}d`],
  ]
  const details = [
    ['LLM calls', formatInt(data.totals.llm_calls)],
    ['Longest streak', `${longest}d`],
    ['Peak day', peakDayLabel],
    ['Favorite model', favoriteModel],
  ]
  const days = buildHeatmap(data)
  const maxTurns = Math.max(...days.map((day) => day.turns), 1)

  return (
    <div className="mt-4">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 @[26rem]/usage:grid-cols-4">
        {stats.map(([label, value]) => (
          <div key={label} className="min-w-0">
            <dt className="truncate text-[11px] text-(--color-text-muted)">{label}</dt>
            <dd className="mt-0.5 truncate text-base font-medium tabular-nums text-(--color-text)" title={value}>
              {value}
            </dd>
          </div>
        ))}
      </dl>

      <div
        className="mt-4 grid grid-flow-col grid-rows-7 gap-[3px]"
        style={{ gridTemplateColumns: `repeat(${HEATMAP_WEEKS}, minmax(0, 1fr))` }}
        role="grid"
        aria-label="Daily turns activity"
      >
        {days.map((day) => {
          const level = heatLevel(day.turns, maxTurns)
          return (
            <div
              key={day.day}
              role="gridcell"
              className={cn(
                'h-2.5 min-w-0 rounded-[3px]',
                level === 0 ? 'bg-(--color-text)/6' : 'bg-(--accent-blue)',
              )}
              style={{ opacity: day.future ? 0.4 : level === 0 ? 1 : 0.25 + level * 0.18 }}
              title={day.future ? day.day : `${day.day}: ${day.turns} turns`}
              aria-label={day.future ? day.day : `${day.day}: ${day.turns} turns`}
            />
          )
        })}
      </div>

      <p className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-(--color-text-muted)">
        {details.map(([label, value]) => (
          <span key={label} className="min-w-0 truncate">
            {label} <span className="text-(--color-text-2)">{value}</span>
          </span>
        ))}
      </p>
    </div>
  )
}

function ModelUsage({ data }: { data: ObservabilitySummary }) {
  const models = [...data.by_model].sort((a, b) => b.calls - a.calls).slice(0, 5)

  if (models.length === 0) {
    return (
      <p className="py-8 text-center text-xs text-(--color-text-subtle)">No model usage in this period.</p>
    )
  }

  const maxCalls = Math.max(...models.map((model) => model.calls), 1)

  return (
    <div className="mt-4 space-y-3">
      {models.map((model) => (
        <div key={model.provider_model}>
          <div className="flex items-center gap-3 text-xs">
            <span className="min-w-0 flex-1 truncate text-(--color-text-2)" title={model.provider_model}>
              {model.provider_model}
            </span>
            <span className="shrink-0 tabular-nums text-(--color-text-muted)">{formatInt(model.calls)} calls</span>
            <span className="w-14 shrink-0 text-right font-medium tabular-nums text-(--color-text)">
              {totalTokens(model.input_tokens, model.output_tokens)}
            </span>
          </div>
          <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-(--color-text)/6">
            <div
              className="h-full rounded-full bg-(--accent-blue)"
              style={{ width: `${Math.max((model.calls / maxCalls) * 100, 4)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}
