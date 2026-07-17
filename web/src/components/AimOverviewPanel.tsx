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
 *
 * Units are the mode's central object, so every card opens a detail
 * panel: the unit's full state, its run history, a jump to its KB doc,
 * and quick actions that pre-fill the right pipeline (via aimHandoff) —
 * the operator never re-types a unit key across surfaces.
 */

import { useMemo, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  BookOpen,
  CircleAlert,
  CircleCheck,
  CircleX,
  FolderGit2,
  FolderInput,
  FolderOutput,
  Link2,
  Loader2,
  Play,
  Search,
  X,
} from 'lucide-react'
import { getAimProjectSummary, listAimRuns, listAimUnits } from '@/api/client'
import { queryKeys } from '@/queries/keys'
import { resolveAimRoleWorkspaces } from '@/components/AimKbPanel'
import { setAimKbOpenPath, setAimPipelinePrefill } from '@/lib/aimHandoff'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { AimPhaseCounts, AimRunListItem, AimUnitOut, CodingProject } from '@/api/types'

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

/** The pipeline that most likely moves this unit forward — quick actions
 * lead with it, the rest stay one click away. */
function nextPipelineFor(phase: string): { key: string; label: string } {
  switch (phase) {
    case 'inventory':
      return { key: 'understand', label: 'Understand' }
    case 'understood':
    case 'designed':
      return { key: 'convert-unit', label: 'Convert' }
    case 'converted':
      return { key: 'compare', label: 'Test-compare' }
    default:
      return { key: 'compare', label: 'Test-compare' }
  }
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
    if (typeof value === 'number' || typeof value === 'string') return `${key} ${value}`
  }
  return null
}

function workspaceName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path
}

function VerdictDot({ verdict }: { verdict: string }) {
  if (verdict === 'pass') return <CircleCheck size={10} className="text-(--color-success)" />
  if (verdict === 'acceptable_diff')
    return <CircleCheck size={10} className="text-(--color-warning,orange)" />
  if (verdict === 'error') return <CircleAlert size={10} className="text-(--color-error)" />
  return <CircleX size={10} className="text-(--color-error)" />
}

export function AimOverviewPanel({ project }: { project: CodingProject }) {
  const navigate = useNavigate()
  const [wave, setWave] = useState<number | 'all'>('all')
  const [moduleFilter, setModuleFilter] = useState<string>('all')
  const [search, setSearch] = useState('')
  const [selectedUnitId, setSelectedUnitId] = useState<string | null>(null)

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
    queryFn: () => listAimRuns(project.id, 50),
    refetchInterval: 10_000,
  })
  const allRuns = useMemo(() => recentRunsQuery.data ?? [], [recentRunsQuery.data])

  const units = useMemo(() => unitsQuery.data ?? [], [unitsQuery.data])
  const waves = [...new Set(units.map((u) => u.wave).filter((w): w is number => w !== null))].sort(
    (a, b) => a - b,
  )
  const modules = useMemo(
    () => [...new Set(units.map((u) => u.module))].sort(),
    [units],
  )
  const visibleUnits = useMemo(() => {
    const query = search.trim().toLowerCase()
    return units.filter(
      (u) =>
        (moduleFilter === 'all' || u.module === moduleFilter) &&
        (!query || `${u.module}/${u.name}`.toLowerCase().includes(query)),
    )
  }, [units, moduleFilter, search])

  const selectedUnit = units.find((u) => u.id === selectedUnitId) ?? null

  const rulebook = (project.settings?.aim as { rulebook?: { id?: string } } | undefined)?.rulebook
  const sources = resolveAimRoleWorkspaces(project, 'source')
  const target = resolveAimRoleWorkspaces(project, 'target')[0]
  const kb = resolveAimRoleWorkspaces(project, 'kb')[0]
  const phaseCounts = summaryQuery.data?.phase_counts
  const totalUnits = summaryQuery.data?.total_units ?? 0

  const goRunPipeline = (pipeline: string, unit?: AimUnitOut) => {
    setAimPipelinePrefill({
      pipeline,
      unit: unit ? `${unit.module}/${unit.name}` : undefined,
      wave: unit?.wave ?? undefined,
    })
    navigate({
      to: '/aim/$projectId/$feature',
      params: { projectId: project.id, feature: 'pipelines' },
    })
  }

  const goOpenKbDoc = (unit: AimUnitOut) => {
    if (unit.kb_doc_path) setAimKbOpenPath(unit.kb_doc_path)
    navigate({
      to: '/aim/$projectId/$feature',
      params: { projectId: project.id, feature: 'kb' },
    })
  }

  return (
    <div className="flex h-full min-h-0">
      <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col">
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
          <div className="flex shrink-0 items-center gap-1.5">
            {/* Unit search — client-side, composes with wave + module. */}
            {units.length > 0 && (
              <span className="relative">
                <Search
                  size={11}
                  className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-(--color-text-subtle)"
                  aria-hidden="true"
                />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Find unit…"
                  className="w-36 rounded bg-(--bg-key) py-1 pl-6 pr-2 text-xs text-(--color-text) placeholder:text-(--color-text-subtle)"
                />
              </span>
            )}
            {modules.length > 1 && (
              <select
                value={moduleFilter}
                onChange={(e) => setModuleFilter(e.target.value)}
                className="rounded bg-(--bg-key) px-2 py-1 text-xs text-(--color-text)"
              >
                <option value="all">Module: all</option>
                {modules.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            )}
            {waves.length > 0 && (
              <select
                value={wave}
                onChange={(e) => setWave(e.target.value === 'all' ? 'all' : Number(e.target.value))}
                className="rounded bg-(--bg-key) px-2 py-1 text-xs text-(--color-text)"
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
        {allRuns.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 border-b border-(--color-border) px-4 py-2">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">
              Recent runs
            </span>
            {allRuns.slice(0, 6).map((run) => (
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
                <VerdictDot verdict={run.verdict} />
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
            <div className="flex h-full flex-col items-center justify-center gap-3">
              <p className="text-xs text-(--color-text-subtle)">
                No units yet — the assess pipeline builds the inventory from the source estate.
              </p>
              <Button size="sm" onClick={() => goRunPipeline('assess')}>
                <Play size={12} />
                Run assess
              </Button>
            </div>
          ) : visibleUnits.length === 0 ? (
            <p className="text-xs text-(--color-text-subtle)">
              No units match the current filters.
            </p>
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {PHASES.map((phase) => {
                const phaseUnits = visibleUnits.filter((u) => u.phase === phase)
                return (
                  <div key={phase} className="min-w-0">
                    <p className="mb-1.5 truncate text-[11px] text-(--color-text-subtle)">
                      {PHASE_LABELS[phase]} · {phaseUnits.length}
                    </p>
                    <div className="space-y-1.5">
                      {phaseUnits.map((unit) => (
                        <UnitCard
                          key={unit.id}
                          unit={unit}
                          selected={unit.id === selectedUnitId}
                          onClick={() =>
                            setSelectedUnitId(unit.id === selectedUnitId ? null : unit.id)
                          }
                        />
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Unit detail — the hub every card opens: full state, run history,
          jump to KB doc, quick pipeline actions with the unit pre-filled. */}
      {selectedUnit && (
        <UnitDetailPanel
          unit={selectedUnit}
          runs={allRuns}
          projectId={project.id}
          onClose={() => setSelectedUnitId(null)}
          onRunPipeline={goRunPipeline}
          onOpenKbDoc={goOpenKbDoc}
          onOpenRun={(runId) =>
            navigate({
              to: '/aim/$projectId/runs/$runId',
              params: { projectId: project.id, runId },
            })
          }
        />
      )}
    </div>
  )
}

function UnitCard({
  unit,
  selected,
  onClick,
}: {
  unit: AimUnitOut
  selected: boolean
  onClick: () => void
}) {
  const complexity = complexityLabel(unit.complexity)
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'w-full rounded px-2 py-1.5 text-left transition-shadow',
        cardTone(unit),
        selected && 'ring-1 ring-(--color-accent)',
      )}
      title={`${unit.module}/${unit.name} — click for details`}
    >
      <p className="flex items-center gap-1 truncate text-xs">
        <span className="min-w-0 flex-1 truncate">
          {unit.module}/{unit.name}
        </span>
        {unit.kb_doc_path && (
          <BookOpen size={10} className="shrink-0 opacity-60" aria-label="Documented in the KB" />
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
    </button>
  )
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[5.5rem_1fr] items-baseline gap-x-2 gap-y-0.5">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">
        {label}
      </span>
      <span className="min-w-0 break-words text-xs text-(--color-text-2)">{children}</span>
    </div>
  )
}

function UnitDetailPanel({
  unit,
  runs,
  onClose,
  onRunPipeline,
  onOpenKbDoc,
  onOpenRun,
}: {
  unit: AimUnitOut
  runs: AimRunListItem[]
  projectId: string
  onClose: () => void
  onRunPipeline: (pipeline: string, unit: AimUnitOut) => void
  onOpenKbDoc: (unit: AimUnitOut) => void
  onOpenRun: (runId: string) => void
}) {
  const unitKey = `${unit.module}/${unit.name}`
  const unitRuns = runs.filter((run) => run.unit === unitKey).slice(0, 8)
  const next = nextPipelineFor(unit.phase)
  const complexityEntries = Object.entries(unit.complexity).filter(
    ([, value]) => typeof value === 'string' || typeof value === 'number',
  )

  return (
    <div className="flex w-80 shrink-0 flex-col border-l border-(--color-border)">
      <div className="flex items-center justify-between gap-2 border-b border-(--color-border) px-3 py-2">
        <p className="min-w-0 truncate font-mono text-xs font-medium text-(--color-text)">
          {unitKey}
        </p>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close unit details"
          className="shrink-0 rounded p-0.5 text-(--color-text-muted) hover:text-(--color-text)"
        >
          <X size={13} />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {/* Quick actions — pre-filled pipeline runs; the likely next step leads. */}
        <div className="flex flex-wrap items-center gap-1.5">
          <Button size="sm" onClick={() => onRunPipeline(next.key, unit)}>
            <Play size={11} />
            {next.label}
          </Button>
          {unit.kb_doc_path && (
            <Button size="sm" variant="secondary" onClick={() => onOpenKbDoc(unit)}>
              <BookOpen size={11} />
              KB doc
            </Button>
          )}
        </div>

        <div className="space-y-1.5 rounded-md bg-(--bg-key) px-3 py-2">
          <DetailRow label="Phase">
            <span className="font-mono">{unit.phase}</span>
          </DetailRow>
          <DetailRow label="Kind">{unit.kind}</DetailRow>
          <DetailRow label="Wave">{unit.wave ?? '—'}</DetailRow>
          <DetailRow label="Assignee">{unit.assignee ?? '—'}</DetailRow>
          {complexityEntries.length > 0 && (
            <DetailRow label="Complexity">
              {complexityEntries.map(([key, value]) => `${key}: ${String(value)}`).join(' · ')}
            </DetailRow>
          )}
          {unit.depends_on.length > 0 && (
            <DetailRow label="Depends on">
              <span className="font-mono text-[11px]">{unit.depends_on.join(', ')}</span>
            </DetailRow>
          )}
        </div>

        {/* Every pipeline, one click, unit pre-filled. */}
        <div>
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">
            Run pipeline
          </p>
          <div className="flex flex-wrap gap-1">
            {[
              { key: 'understand', label: 'understand' },
              { key: 'convert-unit', label: 'convert' },
              { key: 'compare', label: 'test-compare' },
            ].map((p) => (
              <button
                key={p.key}
                type="button"
                onClick={() => onRunPipeline(p.key, unit)}
                className="rounded border border-(--color-border) px-1.5 py-0.5 font-mono text-[10px] text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* This unit's run history. */}
        <div>
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">
            Runs · {unitRuns.length}
          </p>
          {unitRuns.length === 0 ? (
            <p className="text-[11px] text-(--color-text-subtle)">
              No recorded runs for this unit yet.
            </p>
          ) : (
            <div className="space-y-0.5">
              {unitRuns.map((run) => (
                <button
                  key={run.id}
                  type="button"
                  onClick={() => onOpenRun(run.id)}
                  className="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-[11px] text-(--color-text-2) transition-colors hover:bg-(--bg-key)"
                >
                  <VerdictDot verdict={run.verdict} />
                  <span className="min-w-0 flex-1 truncate">
                    {run.kind}
                    {run.case_set ? ` · ${run.case_set}` : ''}
                  </span>
                  <span className="shrink-0 text-[10px] text-(--color-text-subtle)">
                    {new Date(run.created_at).toLocaleTimeString()}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {unit.kb_doc_path && (
          <p className="flex items-center gap-1 text-[10px] text-(--color-text-subtle)">
            <Activity size={9} aria-hidden="true" />
            doc: <span className="truncate font-mono">{unit.kb_doc_path}</span>
          </p>
        )}
      </div>
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
