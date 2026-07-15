import { useState } from 'react'
import { motion } from 'framer-motion'

import EvoFluxLogo from '@/assets/brand/evoflux-app-icon.png'
import type { ObservabilitySummary } from '@/api/client'
import { useReducedMotion } from '@/hooks/useReducedMotion'
import { useObservabilitySummaryQuery } from '@/queries'
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

export function ChatWelcome({ context }: ChatWelcomeProps) {
  const [view, setView] = useState<UsageView>('overview')
  const [period, setPeriod] = useState<UsagePeriod>('all')
  const prefersReducedMotion = useReducedMotion()
  const queryDays = period === 'all' ? 90 : period
  const summary = useObservabilitySummaryQuery(queryDays)

  return (
    <motion.div
      initial={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: prefersReducedMotion ? 0.01 : 0.35, ease: 'easeOut' }}
      className="mx-auto flex w-full max-w-[480px] select-none flex-col items-center gap-6 py-9 sm:py-12"
    >
      <div className="flex flex-col items-center gap-4 text-center">
        <img
          src={EvoFluxLogo}
          className="h-16 w-16 rounded-2xl opacity-95"
          width={64}
          height={64}
          alt=""
          aria-hidden="true"
        />
        <h2 className="font-hand text-3xl font-bold text-(--color-text)">
          what&rsquo;s on your mind?
        </h2>
      </div>

      {context}

      <section
        className="w-full rounded-xl border border-(--color-border-subtle) bg-(--bg-sidebar) p-2 shadow-sm"
        aria-label="Recent usage"
      >
        <div className="mb-1.5 flex items-center justify-between">
          <div className="flex items-center gap-1" role="tablist" aria-label="Usage view">
            {(['overview', 'models'] as const).map((item) => (
              <button
                key={item}
                type="button"
                role="tab"
                aria-selected={view === item}
                onClick={() => setView(item)}
                className={`rounded-md px-2.5 py-1 text-xs capitalize transition-colors ${
                  view === item
                    ? 'bg-(--bg-key) font-medium text-(--color-text) shadow-xs'
                    : 'text-(--color-text-muted) hover:text-(--color-text)'
                }`}
              >
                {item}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1" aria-label="Usage period">
            {([
              ['all', 'All'],
              [30, '30d'],
              [7, '7d'],
            ] as const).map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={period === value}
                onClick={() => setPeriod(value)}
                className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
                  period === value
                    ? 'bg-(--bg-key) font-medium text-(--color-text) shadow-xs'
                    : 'text-(--color-text-muted) hover:text-(--color-text)'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {summary.isLoading ? (
          <div className="space-y-1.5">
            <div className="grid grid-cols-2 gap-1 min-[460px]:grid-cols-4">
              {Array.from({ length: 8 }).map((_, index) => (
                <div key={index} className="h-10 animate-pulse rounded-md bg-(--bg-key) p-2">
                  <div className="h-2 w-12 rounded bg-(--color-border)" />
                  <div className="mt-1.5 h-3 w-8 rounded bg-(--color-border)" />
                </div>
              ))}
            </div>
            <div className="h-[108px] animate-pulse rounded-md bg-(--bg-key)" />
          </div>
        ) : summary.isError || !summary.data ? (
          <div className="flex h-36 items-center justify-center rounded-md bg-(--bg-key)">
            <p className="text-center text-xs text-(--color-text-subtle)">
              Usage data is unavailable.
            </p>
          </div>
        ) : view === 'overview' ? (
          <UsageOverview data={summary.data} queryDays={queryDays} />
        ) : (
          <ModelUsage data={summary.data} />
        )}
      </section>
    </motion.div>
  )
}

function UsageOverview({ data, queryDays }: { data: ObservabilitySummary; queryDays: number }) {
  const activeDayCount = activityDays(data).size
  const { current, longest } = streaks(data, queryDays)
  const favoriteModel = [...data.by_model].sort((a, b) => b.calls - a.calls)[0]?.model ?? '—'
  const peakDay = [...data.daily_turns].sort((a, b) => b.turns - a.turns)[0]
  const peakDayLabel = peakDay
    ? new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(
        new Date(`${peakDay.day}T00:00:00Z`),
      )
    : '—'
  const tokens = totalTokens(data.totals.input_tokens, data.totals.output_tokens)
  const stats = [
    ['Turns', formatInt(data.totals.turns)],
    ['LLM calls', formatInt(data.totals.llm_calls)],
    ['Total tokens', tokens],
    ['Active days', formatInt(activeDayCount)],
    ['Current streak', `${current}d`],
    ['Longest streak', `${longest}d`],
    ['Peak day', peakDayLabel],
    ['Favorite model', favoriteModel],
  ]
  const days = buildHeatmap(data)
  const maxTurns = Math.max(...days.map((day) => day.turns), 1)

  return (
    <div>
      <div className="grid grid-cols-2 gap-1 min-[460px]:grid-cols-4">
        {stats.map(([label, value]) => (
          <div key={label} className="min-w-0 rounded-md bg-(--bg-key) px-2 py-1">
            <p className="truncate text-[11px] leading-3.5 text-(--color-text-muted)" title={label}>
              {label}
            </p>
            <p
              className={`mt-0.5 truncate leading-4 font-semibold text-(--color-text) ${
                label === 'Favorite model' ? 'text-xs' : 'text-sm'
              }`}
              title={value}
            >
              {value}
            </p>
          </div>
        ))}
      </div>

      <div
        className="mt-1.5 grid grid-flow-col grid-rows-7 gap-[3px]"
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
              className={`aspect-square min-w-0 rounded-[2px] ${
                level === 0 ? 'bg-(--bg-key)' : 'bg-(--accent-blue)'
              }`}
              style={{ opacity: day.future ? 0.35 : level === 0 ? 1 : 0.2 + level * 0.2 }}
              title={day.future ? day.day : `${day.day}: ${day.turns} turns`}
              aria-label={day.future ? day.day : `${day.day}: ${day.turns} turns`}
            />
          )
        })}
      </div>

      <p className="mt-1.5 px-0.5 text-[11px] text-(--color-text-muted)">
        You&rsquo;ve used {tokens} tokens across {formatInt(data.totals.turns)} turns.
      </p>
    </div>
  )
}

function ModelUsage({ data }: { data: ObservabilitySummary }) {
  const models = [...data.by_model].sort((a, b) => b.calls - a.calls).slice(0, 5)

  if (models.length === 0) {
    return (
      <div className="flex h-36 items-center justify-center rounded-md bg-(--bg-key)">
        <p className="text-xs text-(--color-text-subtle)">No model usage in this period.</p>
      </div>
    )
  }

  const maxCalls = Math.max(...models.map((model) => model.calls), 1)

  return (
    <div className="space-y-1">
      {models.map((model) => (
        <div key={model.provider_model} className="rounded-md bg-(--bg-key) px-2.5 py-2">
          <div className="flex items-center gap-3 text-xs">
            <span className="min-w-0 flex-1 truncate font-medium text-(--color-text-2)" title={model.provider_model}>
              {model.provider_model}
            </span>
            <span className="shrink-0 text-(--color-text-muted)">{formatInt(model.calls)} calls</span>
            <span className="w-14 shrink-0 text-right font-semibold text-(--color-text)">
              {totalTokens(model.input_tokens, model.output_tokens)}
            </span>
          </div>
          <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-(--color-border-subtle)">
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