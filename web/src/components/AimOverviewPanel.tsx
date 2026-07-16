/**
 * AimOverviewPanel — the project's default feature: a kanban of migration
 * units grouped by phase plus a metric row (aim-mode-shell-ux-spec.md v2.2
 * §5.1). Polls every 10s (spec §6) — SSE upgrades arrive with AIM-5.
 * No chat affordance anywhere: this mode's only chat surface is the
 * post-run Discussion panel in Runs & Reports.
 *
 * Beyond the wireframe minimum the header answers "what is this project
 * wired to?" (source repos / target / KB / rulebook), the metric row is
 * followed by a phase-distribution bar (global, unaffected by the wave
 * filter), and a recent-runs strip deep-links into Runs & Reports.
 */

import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import {
  BookOpen,
  CircleAlert,
  CircleCheck,
  CircleX,
  FolderGit2,
  FolderInput,
  FolderOutput,
  Link2,
  Loader2,
} from 'lucide-react'
import { getAimProjectSummary, listAimRuns, listAimUnits } from '@/api/client'
import { queryKeys } from '@/queries/keys'
import { resolveAimRoleWorkspaces } from '@/components/AimKbPanel'
import { cn } from '@/lib/utils'
import type { AimPhaseCounts, AimUnitOut, CodingProject } from '@/api/types'

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

// Distribution bar segments — muted → accent → success as units progress.
const PHASE_BAR_CLASSES: Record<(typeof PHASES)[number], string> = {
  inventory: 'bg-(--color-text-subtle)/40',
  understood: 'bg-(--color-accent)/40',
  designed: 'bg-(--color-accent)/70',
  converted: 'bg-(--color-accent)',
  equivalent: 'bg-(--color-success)/70',
  cutover: 'bg-(--color-success)',
}

function cardTone(unit: AimUnitOut): string {
  if (unit.phase === 'equivalent' || unit.phase === 'cutover') {
    return 'bg-(--color-success-bg,var(--bg-key)) text-(--color-success,inherit)'
  }
  return 'bg-(--bg-key)'
}

/** Pull a readable size out of the unit's complexity dict, whichever of the
 * common keys the extractor filled. */
function complexityLabel(complexity: Record<string, unknown>): string | null {
  for (const key of ['loc', 'lines', 'score', 'points']) {
    const value = complexity[key]
    if (typeof value === 'number') return `${key} ${value}`
  }
  return null
}

function workspaceName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path
}

export function AimOverviewPanel({ project }: { project: CodingProject }) {
  const navigate = useNavigate()
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

  const recentRunsQuery = useQuery({
    queryKey: [...queryKeys.projects.detail(project.id), 'aim-recent-runs'],
    queryFn: () => listAimRuns(project.id, 6),
    refetchInterval: 10_000,
  })

  const units = unitsQuery.data ?? []
  const waves = [...new Set(units.map((u) => u.wave).filter((w): w is number => w !== null))].sort(
    (a, b) => a - b,
  )
  const rulebook = (project.settings?.aim as { rulebook?: { id?: string } } | undefined)?.rulebook
  const sources = resolveAimRoleWorkspaces(project, 'source')
  const target = resolveAimRoleWorkspaces(project, 'target')[0]
  const kb = resolveAimRoleWorkspaces(project, 'kb')[0]
  const phaseCounts = summaryQuery.data?.phase_counts
  const totalUnits = summaryQuery.data?.total_units ?? 0

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-(--color-border) px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-medium text-(--color-text)">{project.name}</span>
          {rulebook?.id && (
            <span
              className="flex shrink-0 items-center gap-1 rounded bg-(--bg-key) px-2 py-0.5 text-[10px] text-(--color-text-subtle)"
              title={`Rulebook: ${rulebook.id}`}
            >
              <BookOpen size={10} aria-hidden="true" />
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

      {/* What this project is wired to — repos by role. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-(--color-border) px-4 py-2 text-[11px] text-(--color-text-muted)">
        <span
          className="flex items-center gap-1.5"
          title={sources.map((s) => s.path).join('\n') || 'No source repos mapped on this machine'}
        >
          <FolderInput size={11} className="shrink-0 text-(--color-text-subtle)" />
          {sources.length > 0
            ? `${sources.length} source ${sources.length === 1 ? 'repo' : 'repos'}: ${sources
                .map((s) => workspaceName(s.path))
                .join(', ')}`
            : 'no source repos'}
          <span className="rounded bg-(--bg-key) px-1 py-px text-[9px] text-(--color-text-subtle)">
            read-only
          </span>
        </span>
        <span
          className="flex items-center gap-1.5"
          title={target?.path ?? 'No target repo mapped on this machine'}
        >
          <FolderOutput size={11} className="shrink-0 text-(--color-text-subtle)" />
          target: {target ? workspaceName(target.path) : '—'}
        </span>
        <span className="flex items-center gap-1.5" title={kb?.path ?? 'No KB repo mapped on this machine'}>
          <FolderGit2 size={11} className="shrink-0 text-(--color-text-subtle)" />
          KB: {kb ? workspaceName(kb.path) : '—'}
        </span>
      </div>

      <div className="grid shrink-0 grid-cols-2 gap-2 border-b border-(--color-border) p-3 sm:grid-cols-4">
        {summaryQuery.isLoading ? (
          <p className="col-span-4 text-xs text-(--color-text-subtle)">Loading summary…</p>
        ) : summaryQuery.isError ? (
          <p className="col-span-4 text-xs text-(--color-error)">Failed to load summary</p>
        ) : (
          <>
            <MetricCard label="Total units" value={totalUnits} />
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
            {phaseCounts && totalUnits > 0 && (
              <div className="col-span-2 sm:col-span-4">
                <PhaseBar counts={phaseCounts} total={totalUnits} />
              </div>
            )}
          </>
        )}
      </div>

      {/* Recent runs — one line each, deep-links into Runs & Reports. */}
      {(recentRunsQuery.data?.length ?? 0) > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 border-b border-(--color-border) px-4 py-2">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">
            Recent runs
          </span>
          {(recentRunsQuery.data ?? []).map((run) => (
            <button
              key={run.id}
              type="button"
              onClick={() =>
                navigate({
                  to: '/aim/$projectId/runs/$runId',
                  params: { projectId: project.id, runId: run.id },
                })
              }
              className="flex items-center gap-1 rounded bg-(--bg-key) px-1.5 py-0.5 text-[11px] text-(--color-text-2) transition-colors hover:text-(--color-text)"
              title={`${run.unit} · ${run.kind} · ${new Date(run.created_at).toLocaleString()}`}
            >
              {run.verdict === 'pass' ? (
                <CircleCheck size={10} className="text-(--color-success)" />
              ) : run.verdict === 'acceptable_diff' ? (
                <CircleCheck size={10} className="text-(--color-warning,orange)" />
              ) : run.verdict === 'error' ? (
                <CircleAlert size={10} className="text-(--color-error)" />
              ) : (
                <CircleX size={10} className="text-(--color-error)" />
              )}
              <span className="max-w-40 truncate">{run.unit}</span>
              <span className="text-(--color-text-subtle)">{run.kind}</span>
            </button>
          ))}
        </div>
      )}

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
                      <UnitCard key={unit.id} unit={unit} />
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

function UnitCard({ unit }: { unit: AimUnitOut }) {
  const complexity = complexityLabel(unit.complexity)
  const tooltip = [
    `${unit.module}/${unit.name}`,
    `kind: ${unit.kind}`,
    unit.wave !== null ? `wave ${unit.wave}` : null,
    unit.assignee ? `assignee: ${unit.assignee}` : null,
    unit.depends_on.length ? `deps: ${unit.depends_on.join(', ')}` : null,
    complexity,
    unit.kb_doc_path ? `doc: ${unit.kb_doc_path}` : null,
  ]
    .filter(Boolean)
    .join('\n')

  return (
    <div className={cn('rounded px-2 py-1.5', cardTone(unit))} title={tooltip}>
      <p className="flex items-center gap-1 truncate text-xs">
        <span className="min-w-0 flex-1 truncate">
          {unit.module}/{unit.name}
        </span>
        {unit.kb_doc_path && (
          <BookOpen
            size={10}
            className="shrink-0 opacity-60"
            aria-label="Documented in the KB"
          />
        )}
      </p>
      <p className="truncate text-[10px] opacity-70">
        {unit.kind}
        {unit.wave !== null ? ` · w${unit.wave}` : ''}
        {complexity ? ` · ${complexity}` : ''}
        {unit.depends_on.length > 0 && (
          <span title={unit.depends_on.join(', ')}>
            {' · '}
            <Link2 size={9} className="inline" aria-hidden="true" /> {unit.depends_on.length}
          </span>
        )}
        {unit.assignee ? ` · ${unit.assignee}` : ''}
      </p>
    </div>
  )
}

function PhaseBar({ counts, total }: { counts: AimPhaseCounts; total: number }) {
  return (
    <div>
      <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-(--bg-key)">
        {PHASES.map((phase) => {
          const count = counts[phase]
          if (!count) return null
          return (
            <div
              key={phase}
              className={PHASE_BAR_CLASSES[phase]}
              style={{ width: `${(count / total) * 100}%` }}
              title={`${PHASE_LABELS[phase]}: ${count}`}
            />
          )
        })}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
        {PHASES.map((phase) => (
          <span key={phase} className="flex items-center gap-1 text-[10px] text-(--color-text-subtle)">
            <span className={cn('h-1.5 w-1.5 rounded-full', PHASE_BAR_CLASSES[phase])} />
            {PHASE_LABELS[phase]} {counts[phase]}
          </span>
        ))}
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
