import { useState } from 'react'
import { motion } from 'framer-motion'
import { MessageSquareText, Paperclip, Sparkles } from 'lucide-react'

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

export function ChatWelcome({ context }: ChatWelcomeProps) {
  const preset = useMotionPreset()
  const enter = fadeRise(preset, 12)

  return (
    <motion.div
      initial={enter.initial}
      animate={enter.animate}
      transition={enter.transition}
      className="relative mx-auto w-full max-w-[620px] select-none"
    >
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
        <div className="absolute top-1/2 left-1/2 h-96 w-96 -translate-x-1/2 -translate-y-1/2 rounded-full bg-(--color-accent)/8 blur-3xl" />
      </div>

      <div className="@container/work-empty relative overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-card)/95 shadow-md shadow-black/8">
        <div className="absolute inset-x-0 top-0 h-px bg-linear-to-r from-transparent via-(--color-accent)/60 to-transparent" aria-hidden="true" />

        <div className="grid @[36rem]/work-empty:grid-cols-[minmax(13rem,0.68fr)_minmax(22.5rem,1.32fr)]">
          <section className="flex flex-col border-b border-(--color-border-subtle) p-3 @[36rem]/work-empty:border-r @[36rem]/work-empty:border-b-0">
            <div className="flex items-start gap-2">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-(--color-accent)/12 text-(--color-accent) shadow-sm shadow-(--color-accent)/10 ring-1 ring-(--color-accent)/20 ring-inset">
                <img
                  src={EvoFluxLogo}
                  className="h-6 w-6 rounded-md"
                  width={24}
                  height={24}
                  alt=""
                  aria-hidden="true"
                />
              </div>
              <div className="min-w-0">
                <div className="inline-flex w-fit items-center gap-1 rounded-full border border-(--color-border-subtle) bg-(--bg-page)/70 px-2 py-0.5 text-[0.56rem] font-semibold tracking-[0.12em] text-(--color-text-muted) uppercase">
                  <Sparkles size={9} aria-hidden="true" />
                  Work mode
                </div>
                <h2 className="mt-0.5 text-sm leading-4.5 font-semibold tracking-tight text-(--color-text)">
                  What would you like to accomplish?
                </h2>
              </div>
            </div>

            <p className="mt-1.5 text-[10px] leading-3.5 text-(--color-text-muted)">
              Start with the outcome. EvoFlux will plan the work and carry the task through.
            </p>

            {context && <div className="mt-2">{context}</div>}

            <div className="mt-2 grid gap-1 @[28rem]/work-empty:grid-cols-2 @[36rem]/work-empty:grid-cols-1">
              <div className="flex items-center gap-2 rounded-lg bg-(--bg-page)/55 px-2 py-1.5">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-(--bg-key) text-(--color-accent) ring-1 ring-(--color-border)">
                  <MessageSquareText size={11} strokeWidth={2} aria-hidden="true" />
                </span>
                <p className="text-[10px] font-semibold text-(--color-text)">Describe the outcome</p>
              </div>
              <div className="flex items-center gap-2 rounded-lg bg-(--bg-page)/55 px-2 py-1.5">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-(--bg-key) text-(--color-accent) ring-1 ring-(--color-border)">
                  <Paperclip size={11} strokeWidth={2} aria-hidden="true" />
                </span>
                <p className="text-[10px] font-semibold text-(--color-text)">Add useful context</p>
              </div>
            </div>
          </section>

          <div className="flex items-center p-1.5 @[36rem]/work-empty:p-2">
            <RecentUsageCard className="relative border-0 bg-transparent p-0 shadow-none" />
          </div>
        </div>
      </div>
    </motion.div>
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
        '@container/usage w-full rounded-xl border border-(--color-border-subtle) bg-(--bg-sidebar) p-2 shadow-sm',
        className,
      )}
      aria-label="Recent usage"
    >
        <div className="mb-1 flex items-center justify-between">
          <div className="flex items-center gap-1" role="tablist" aria-label="Usage view">
            {(['overview', 'models'] as const).map((item) => (
              <button
                key={item}
                type="button"
                role="tab"
                aria-selected={view === item}
                onClick={() => setView(item)}
                className={`rounded-md px-2 py-0.5 text-[11px] capitalize transition-colors ${
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
                className={`rounded-md px-2 py-0.5 text-[11px] transition-colors ${
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
            <div className="grid grid-cols-2 gap-1 @[24rem]/usage:grid-cols-4">
              {Array.from({ length: 8 }).map((_, index) => (
                <div key={index} className="h-8 animate-pulse rounded-md bg-(--bg-key) p-1.5">
                  <div className="h-2 w-12 rounded bg-(--color-border)" />
                  <div className="mt-1.5 h-3 w-8 rounded bg-(--color-border)" />
                </div>
              ))}
            </div>
            <div className="h-[74px] animate-pulse rounded-md bg-(--bg-key)" />
          </div>
        ) : summary.isError || !summary.data ? (
          <div className="flex h-28 items-center justify-center rounded-md bg-(--bg-key)">
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
      <div className="grid grid-cols-2 gap-1 @[24rem]/usage:grid-cols-4">
        {stats.map(([label, value]) => (
          <div key={label} className="min-w-0 rounded-md bg-(--bg-key) px-1.5 py-0.5">
            <p className="truncate text-[10px] leading-3 text-(--color-text-muted)" title={label}>
              {label}
            </p>
            <p
              className={`mt-0.5 truncate leading-3.5 font-semibold text-(--color-text) ${
                label === 'Favorite model' ? 'text-[10px]' : 'text-xs'
              }`}
              title={value}
            >
              {value}
            </p>
          </div>
        ))}
      </div>

      <div
        className="mt-1 grid grid-flow-col grid-rows-7 gap-[3px]"
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
              className={`h-2 min-w-0 rounded-[2px] ${
                level === 0 ? 'bg-(--bg-key)' : 'bg-(--accent-blue)'
              }`}
              style={{ opacity: day.future ? 0.35 : level === 0 ? 1 : 0.2 + level * 0.2 }}
              title={day.future ? day.day : `${day.day}: ${day.turns} turns`}
              aria-label={day.future ? day.day : `${day.day}: ${day.turns} turns`}
            />
          )
        })}
      </div>

      <p className="mt-1 px-0.5 text-[10px] text-(--color-text-muted)">
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
