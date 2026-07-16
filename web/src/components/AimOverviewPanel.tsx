/**
 * AimOverviewPanel — the project's default feature: a kanban of migration
 * units grouped by phase plus a metric row (aim-mode-shell-ux-spec.md v2.2
 * §5.1). Polls every 10s (spec §6) — SSE upgrades arrive with AIM-5.
 * No chat affordance anywhere: this mode's only chat surface is the
 * post-run Discussion panel in Runs & Reports.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { getAimProjectSummary, listAimUnits } from '@/api/client'
import { queryKeys } from '@/queries/keys'
import type { AimUnitOut, CodingProject } from '@/api/types'

const PHASES = [
  'inventory',
  'understood',
  'designed',
  'converted',
  'equivalent',
  'cutover',
] as const

const PHASE_LABELS: Record<(typeof PHASES)[number], string> = {
  inventory: 'Inventory',
  understood: 'Understood',
  designed: 'Designed',
  converted: 'Converted',
  equivalent: 'Equivalent',
  cutover: 'Cutover',
}

function cardTone(unit: AimUnitOut): string {
  if (unit.phase === 'equivalent' || unit.phase === 'cutover') {
    return 'bg-(--color-success-bg,var(--bg-key)) text-(--color-success,inherit)'
  }
  return 'bg-(--bg-key)'
}

export function AimOverviewPanel({ project }: { project: CodingProject }) {
  const [wave, setWave] = useState<number | 'all'>('all')

  const summaryQuery = useQuery({
    queryKey: queryKeys.projects.aimSummary(project.id),
    queryFn: () => getAimProjectSummary(project.id),
    refetchInterval: 10_000,
  })

  const unitsQuery = useQuery({
    queryKey: queryKeys.projects.aimUnits(project.id, wave === 'all' ? undefined : wave),
    queryFn: () => listAimUnits(project.id, wave === 'all' ? undefined : { wave }),
    refetchInterval: 10_000,
  })

  const units = unitsQuery.data ?? []
  const waves = [...new Set(units.map((u) => u.wave).filter((w): w is number => w !== null))].sort(
    (a, b) => a - b,
  )
  const rulebook = (project.settings?.aim as { rulebook?: { id?: string } } | undefined)?.rulebook

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-(--color-border) px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-medium text-(--color-text)">{project.name}</span>
          {rulebook?.id && (
            <span className="shrink-0 rounded bg-(--bg-key) px-2 py-0.5 text-[10px] text-(--color-text-subtle)">
              {rulebook.id}
            </span>
          )}
        </div>
        {waves.length > 0 && (
          <select
            value={wave}
            onChange={(e) => setWave(e.target.value === 'all' ? 'all' : Number(e.target.value))}
            className="shrink-0 rounded bg-(--bg-key) px-2 py-1 text-xs text-(--color-text)"
          >
            <option value="all">Wave: all</option>
            {waves.map((w) => (
              <option key={w} value={w}>
                Wave {w}
              </option>
            ))}
          </select>
        )}
      </div>

      <div className="grid shrink-0 grid-cols-2 gap-2 border-b border-(--color-border) p-3 sm:grid-cols-4">
        {summaryQuery.isLoading ? (
          <p className="col-span-4 text-xs text-(--color-text-subtle)">Loading summary…</p>
        ) : summaryQuery.isError ? (
          <p className="col-span-4 text-xs text-(--color-error)">Failed to load summary</p>
        ) : (
          <>
            <MetricCard label="Total units" value={summaryQuery.data?.total_units ?? 0} />
            <MetricCard
              label="Equivalent"
              value={`${summaryQuery.data?.equivalent_pct.toFixed(1) ?? '0.0'}%`}
            />
            <MetricCard label="Waves" value={waves.length} />
            <MetricCard
              label="Latest run"
              value={
                summaryQuery.data?.latest_run_at
                  ? new Date(summaryQuery.data.latest_run_at).toLocaleTimeString()
                  : '—'
              }
            />
          </>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-3">
        {unitsQuery.isLoading ? (
          <p className="flex items-center gap-1.5 text-xs text-(--color-text-subtle)">
            <Loader2 size={12} className="animate-spin" />
            Loading units…
          </p>
        ) : unitsQuery.isError ? (
          <p className="text-xs text-(--color-error)">Failed to load units</p>
        ) : units.length === 0 ? (
          <p className="text-xs text-(--color-text-subtle)">
            No units yet — run the assess pipeline to build the inventory.
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {PHASES.map((phase) => {
              const phaseUnits = units.filter((u) => u.phase === phase)
              return (
                <div key={phase} className="min-w-0">
                  <p className="mb-1.5 truncate text-[11px] text-(--color-text-subtle)">
                    {PHASE_LABELS[phase]} · {phaseUnits.length}
                  </p>
                  <div className="space-y-1.5">
                    {phaseUnits.map((unit) => (
                      <div
                        key={unit.id}
                        className={`rounded px-2 py-1.5 ${cardTone(unit)}`}
                        title={`${unit.module}/${unit.name}${unit.assignee ? ` · ${unit.assignee}` : ''}`}
                      >
                        <p className="truncate text-xs">
                          {unit.module}/{unit.name}
                        </p>
                        <p className="truncate text-[10px] opacity-70">
                          {unit.kind}
                          {unit.wave !== null ? ` · w${unit.wave}` : ''}
                          {unit.assignee ? ` · ${unit.assignee}` : ''}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded bg-(--bg-key) px-3 py-2">
      <p className="text-[10px] text-(--color-text-subtle)">{label}</p>
      <p className="text-base font-medium text-(--color-text)">{value}</p>
    </div>
  )
}
