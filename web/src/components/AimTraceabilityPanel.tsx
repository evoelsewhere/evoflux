import { useMemo, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleX,
  Database,
  FileCheck2,
  FileText,
  FlaskConical,
  Link2,
  Loader2,
  Map,
  Play,
  RefreshCw,
  Search,
  ShieldAlert,
  Waypoints,
} from 'lucide-react'
import { getAimTraceability, reindexAimProject } from '@/api/client'
import { setAimKbOpenPath, setAimPipelinePrefill } from '@/lib/aimHandoff'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import type { AimTraceabilityIssue, AimTraceabilityUnit, CodingProject } from '@/api/types'

type IssueFilter = 'all' | 'attention' | 'blocker' | 'warning'

const ISSUE_PRIORITY: Record<AimTraceabilityIssue['severity'], number> = {
  blocker: 0,
  warning: 1,
  info: 2,
}

function pipelineLabel(pipeline: string): string {
  return pipeline
    .replace(/^aim-/, '')
    .split('-')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

export function AimTraceabilityPanel({ project }: { project: CodingProject }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [phase, setPhase] = useState('all')
  const [issueFilter, setIssueFilter] = useState<IssueFilter>('all')
  const [selectedKey, setSelectedKey] = useState<string | null>(null)

  const traceabilityQuery = useQuery({
    queryKey: ['projects', 'detail', project.id, 'aim-traceability'],
    queryFn: () => getAimTraceability(project.id),
    refetchInterval: 30_000,
  })
  const reindexMutation = useMutation({
    mutationFn: () => reindexAimProject(project.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['projects', 'detail', project.id, 'aim-traceability'],
      })
      void queryClient.invalidateQueries({
        queryKey: ['projects', 'detail', project.id, 'aim-units'],
      })
    },
  })
  const units = useMemo(() => traceabilityQuery.data?.units ?? [], [traceabilityQuery.data])
  const phases = useMemo(
    () => [...new Set(units.map((unit) => unit.phase))].sort(),
    [units],
  )
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase()
    return units.filter(
      (unit) =>
        (phase === 'all' || unit.phase === phase) &&
        (issueFilter === 'all' ||
          (issueFilter === 'attention' && unit.issues.some((issue) => issue.severity !== 'info')) ||
          unit.issues.some((issue) => issue.severity === issueFilter)) &&
        (!query ||
          unit.unit.toLowerCase().includes(query) ||
          unit.rules.some((rule) => `${rule.id} ${rule.title}`.toLowerCase().includes(query)) ||
          unit.issues.some((issue) => issue.message.toLowerCase().includes(query)) ||
          unit.dependent_units.some((dependent) => dependent.toLowerCase().includes(query)) ||
          unit.target_paths.some((path) => path.toLowerCase().includes(query))),
    )
  }, [issueFilter, phase, search, units])
  const selected = units.find((unit) => unit.unit === selectedKey) ?? null
  const attention = useMemo(
    () =>
      [
        ...(traceabilityQuery.data?.project_issues ?? []).map((issue) => ({
          unit: null,
          issue,
        })),
        ...units.flatMap((unit) =>
          unit.issues
            .filter((issue) => issue.severity !== 'info')
            .map((issue) => ({ unit, issue })),
        ),
      ]
        .filter((item) => item.issue.severity !== 'info')
        .sort(
          (left, right) =>
            ISSUE_PRIORITY[left.issue.severity] - ISSUE_PRIORITY[right.issue.severity] ||
            (right.unit?.impact_count ?? 0) - (left.unit?.impact_count ?? 0) ||
            (left.unit?.unit ?? '').localeCompare(right.unit?.unit ?? ''),
        ),
    [traceabilityQuery.data?.project_issues, units],
  )

  const openKb = (path: string | null) => {
    if (!path) return
    setAimKbOpenPath(path)
    navigate({
      to: '/aim/$projectId/$feature',
      params: { projectId: project.id, feature: 'kb' },
    })
  }
  const openRun = (runId: string | null) => {
    if (!runId) return
    navigate({
      to: '/aim/$projectId/runs/$runId',
      params: { projectId: project.id, runId },
    })
  }
  const runNext = (unit: AimTraceabilityUnit, pipeline?: string | null) => {
    const selectedPipeline = pipeline ?? unit.next_action?.pipeline
    if (!selectedPipeline) return
    setAimPipelinePrefill({
      pipeline: selectedPipeline,
      unit: unit.unit,
      wave: unit.wave ?? undefined,
    })
    navigate({
      to: '/aim/$projectId/$feature',
      params: { projectId: project.id, feature: 'pipelines' },
    })
  }

  if (traceabilityQuery.isLoading) return <TraceabilitySkeleton />
  if (traceabilityQuery.isError) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center text-xs text-(--color-error)">
        Traceability data could not be loaded.
      </div>
    )
  }

  const summary = traceabilityQuery.data?.summary
  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-(--color-border)">
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-(--color-border) bg-(--bg-key) text-(--color-accent)">
              <Waypoints size={15} aria-hidden="true" />
            </span>
            <div>
              <h1 className="text-sm font-semibold text-(--color-text)">Traceability</h1>
              <p className="text-[10px] text-(--color-text-subtle)">
                Unit → rule → mapping → evidence coverage
              </p>
            </div>
          </div>
          <div className="flex w-full flex-wrap items-center gap-2 md:w-auto">
            <button
              type="button"
              onClick={() => reindexMutation.mutate()}
              disabled={reindexMutation.isPending}
              aria-label="Reindex traceability"
              title="Rebuild unit, run, and link indexes from the KB"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-(--color-border) text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-50"
            >
              {reindexMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            </button>
            <div className="relative min-w-48 flex-1 md:w-64 md:flex-none">
              <Search size={12} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-(--color-text-subtle)" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search units, rules, target paths…"
                className="h-8 pl-8 text-xs"
                aria-label="Search traceability"
              />
            </div>
            <Select value={phase} onValueChange={(value) => setPhase(value ?? 'all')}>
              <SelectTrigger size="sm" className="w-32" aria-label="Filter traceability by phase">
                <SelectValue>{phase === 'all' ? 'All phases' : phase}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All phases</SelectItem>
                {phases.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}
              </SelectContent>
            </Select>
            <div className="inline-flex h-8 rounded-md border border-(--color-border) bg-(--bg-key)/55 p-0.5">
              {(
                [
                  ['all', 'All'],
                  ['attention', 'Attention'],
                  ['blocker', 'Blockers'],
                  ['warning', 'Warnings'],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setIssueFilter(value)}
                  aria-pressed={issueFilter === value}
                  className={cn(
                    'rounded px-2 text-[10px] font-medium transition-colors',
                    issueFilter === value
                      ? 'bg-(--bg-page) text-(--color-text) shadow-sm'
                      : 'text-(--color-text-muted) hover:text-(--color-text)',
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
        {summary && (
          <div className="grid grid-cols-2 divide-x divide-y divide-(--color-border) border-t border-(--color-border) sm:grid-cols-4 sm:divide-y-0 lg:grid-cols-8">
            <TraceMetric label="Units" value={summary.total_units} />
            <TraceMetric label="Blockers" value={summary.blocker_count} tone={summary.blocker_count ? 'blocker' : 'ok'} />
            <TraceMetric label="Warnings" value={summary.warning_count} tone={summary.warning_count ? 'warn' : 'ok'} />
            <TraceMetric label="At risk" value={summary.at_risk_units} tone={summary.at_risk_units ? 'warn' : 'ok'} />
            <TraceMetric label="Actions ready" value={summary.ready_actions} tone="ok" />
            <TraceMetric label="Rules reviewed" value={summary.reviewed_units} />
            <TraceMetric label="Mapped" value={summary.mapped_units} />
            <TraceMetric label="With evidence" value={summary.evidenced_units} />
          </div>
        )}
      </header>

      <AttentionQueue
        items={attention}
        onSelect={(unit) => setSelectedKey(unit.unit)}
        onRun={runNext}
      />

      <div className="flex min-h-0 flex-1">
        <section className={cn('min-h-0 min-w-0 flex-1 overflow-y-auto', selected && 'hidden lg:block')}>
          <div className="sticky top-0 z-10 grid grid-cols-[minmax(0,1fr)_repeat(4,2.5rem)_2rem] items-center border-b border-(--color-border) bg-(--bg-page)/95 px-3 py-2 text-[9px] font-medium uppercase text-(--color-text-subtle) backdrop-blur-sm">
            <span>{filtered.length} units</span>
            <span className="text-center" title="Documentation">Doc</span>
            <span className="text-center" title="Business-rule review">Rules</span>
            <span className="text-center" title="Target mapping">Map</span>
            <span className="text-center" title="Passing compare evidence">Test</span>
            <span />
          </div>
          {filtered.length === 0 ? (
            <p className="px-4 py-10 text-center text-xs text-(--color-text-subtle)">No units match these filters.</p>
          ) : filtered.map((unit) => (
            <TraceabilityRow
              key={unit.unit}
              unit={unit}
              selected={unit.unit === selectedKey}
              onClick={() => setSelectedKey(unit.unit)}
            />
          ))}
        </section>

        <aside className={cn('min-h-0 min-w-0 flex-1 overflow-y-auto border-l border-(--color-border) bg-(--bg-subtle)/25 lg:max-w-[46%]', !selected && 'hidden lg:block')}>
          {selected ? (
            <TraceabilityDetail
              unit={selected}
              onBack={() => setSelectedKey(null)}
              onOpenKb={openKb}
              onOpenRun={openRun}
              onRunNext={runNext}
            />
          ) : (
            <div className="flex h-full items-center justify-center px-6 text-center">
              <div>
                <Waypoints size={22} className="mx-auto text-(--color-text-subtle)" />
                <p className="mt-2 text-xs text-(--color-text-muted)">Select a unit to inspect its evidence chain.</p>
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}

function TraceMetric({ label, value, tone }: { label: string; value: number; tone?: 'ok' | 'warn' | 'blocker' }) {
  return (
    <div className="px-3 py-2">
      <p className="text-[9px] uppercase text-(--color-text-subtle)">{label}</p>
      <p className={cn('mt-0.5 font-mono text-sm font-semibold text-(--color-text)', tone === 'ok' && 'text-(--color-success)', tone === 'warn' && 'text-(--color-warning)', tone === 'blocker' && 'text-(--color-error)')}>{value}</p>
    </div>
  )
}

function AttentionQueue({
  items,
  onSelect,
  onRun,
}: {
  items: { unit: AimTraceabilityUnit | null; issue: AimTraceabilityIssue }[]
  onSelect: (unit: AimTraceabilityUnit) => void
  onRun: (unit: AimTraceabilityUnit, pipeline?: string | null) => void
}) {
  if (items.length === 0) {
    return (
      <div className="flex shrink-0 items-center gap-2 border-b border-(--color-border) bg-(--color-success-subtle)/15 px-4 py-2 text-[10px] text-(--color-success)">
        <CircleCheck size={12} /> No blocking or warning diagnostics are open.
      </div>
    )
  }
  return (
    <section className="shrink-0 border-b border-(--color-border) bg-(--bg-subtle)/30 px-4 py-2.5">
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase text-(--color-text-subtle)">
          <ShieldAlert size={12} className="text-(--color-warning)" />
          Attention queue
        </span>
        <span className="text-[9px] text-(--color-text-subtle)">{items.length} diagnostic{items.length === 1 ? '' : 's'}</span>
      </div>
      <div className="flex gap-2 overflow-x-auto pb-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {items.slice(0, 8).map(({ unit, issue }) => (
          <div
            key={`${unit?.unit ?? 'project'}:${issue.code}:${issue.message}`}
            className={cn(
              'flex w-64 shrink-0 items-center gap-2 rounded-md border px-2.5 py-2',
              issue.severity === 'blocker'
                ? 'border-(--color-error)/30 bg-(--color-error-subtle)/20'
                : 'border-(--color-warning)/30 bg-(--color-warning-subtle)/20',
            )}
          >
            {issue.severity === 'blocker' ? <CircleX size={12} className="shrink-0 text-(--color-error)" /> : <CircleAlert size={12} className="shrink-0 text-(--color-warning)" />}
            <button type="button" disabled={!unit} onClick={() => unit && onSelect(unit)} className="min-w-0 flex-1 text-left disabled:cursor-default">
              <span className="block truncate font-mono text-[10px] font-medium text-(--color-text)">{unit?.unit ?? 'Project integrity'}</span>
              <span className="mt-0.5 block truncate text-[9px] text-(--color-text-muted)" title={issue.message}>{issue.message}</span>
            </button>
            {issue.pipeline && unit && (
              <button
                type="button"
                onClick={() => onRun(unit, issue.pipeline)}
                title={`Open ${pipelineLabel(issue.pipeline)}`}
                aria-label={`Open ${pipelineLabel(issue.pipeline)} for ${unit.unit}`}
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
              >
                <Play size={11} />
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

function CoverageState({ ok, neutral = false }: { ok: boolean; neutral?: boolean }) {
  return neutral ? (
    <span className="mx-auto block h-1.5 w-1.5 rounded-full bg-(--color-border-strong)" />
  ) : ok ? (
    <CircleCheck size={13} className="mx-auto text-(--color-success)" aria-label="Covered" />
  ) : (
    <CircleAlert size={13} className="mx-auto text-(--color-warning)" aria-label="Missing" />
  )
}

function TraceabilityRow({ unit, selected, onClick }: { unit: AimTraceabilityUnit; selected: boolean; onClick: () => void }) {
  const phaseRank = ['inventory', 'understood', 'designed', 'converted', 'equivalent', 'cutover'].indexOf(unit.phase)
  const blockers = unit.issues.filter((issue) => issue.severity === 'blocker').length
  const warnings = unit.issues.filter((issue) => issue.severity === 'warning').length
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn('grid w-full grid-cols-[minmax(0,1fr)_repeat(4,2.5rem)_2rem] items-center border-b border-(--color-border) px-3 py-2.5 text-left transition-colors hover:bg-(--bg-key)/55', selected && 'bg-(--bg-key)')}
    >
      <span className="min-w-0">
        <span className="block truncate font-mono text-xs font-medium text-(--color-text)">{unit.unit}</span>
        <span className="mt-0.5 flex items-center gap-1.5 text-[9px] text-(--color-text-subtle)">
          {unit.phase}{unit.wave !== null ? ` · wave ${unit.wave}` : ''}
          {unit.indexed_phase !== unit.phase && <span className="text-(--color-warning)">· index {unit.indexed_phase}</span>}
          {blockers > 0 && <span className="text-(--color-error)">· {blockers} block{blockers === 1 ? '' : 's'}</span>}
          {blockers === 0 && warnings > 0 && <span className="text-(--color-warning)">· {warnings} warning{warnings === 1 ? '' : 's'}</span>}
          {unit.impact_count > 0 && <span className="text-(--color-info)">· impacts {unit.impact_count}</span>}
        </span>
      </span>
      <CoverageState ok={Boolean(unit.doc_path)} />
      <CoverageState ok={unit.rules_reviewed} neutral={phaseRank < 1} />
      <CoverageState ok={Boolean(unit.mapping_path)} neutral={phaseRank < 2} />
      <CoverageState ok={Boolean(unit.passing_run_id)} neutral={phaseRank < 4} />
      <ChevronRight size={13} className="justify-self-end text-(--color-text-subtle)" />
    </button>
  )
}

function TraceabilityDetail({
  unit,
  onBack,
  onOpenKb,
  onOpenRun,
  onRunNext,
}: {
  unit: AimTraceabilityUnit
  onBack: () => void
  onOpenKb: (path: string | null) => void
  onOpenRun: (runId: string | null) => void
  onRunNext: (unit: AimTraceabilityUnit, pipeline?: string | null) => void
}) {
  const blockers = unit.issues.filter((issue) => issue.severity === 'blocker')
  const warnings = unit.issues.filter((issue) => issue.severity === 'warning')
  return (
    <div className="p-4">
      <button type="button" onClick={onBack} className="mb-3 inline-flex items-center gap-1 text-xs text-(--color-text-muted) hover:text-(--color-text) lg:hidden">
        <ArrowLeft size={13} /> Back
      </button>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate font-mono text-sm font-semibold text-(--color-text)">{unit.unit}</h2>
          <p className="mt-1 text-[10px] text-(--color-text-subtle)">{unit.kind} · {unit.phase}{unit.wave !== null ? ` · wave ${unit.wave}` : ''}</p>
        </div>
        <span className={cn('rounded border px-2 py-1 text-[10px] font-medium', unit.gaps.length ? 'border-(--color-warning)/35 bg-(--color-warning-subtle)/25 text-(--color-warning)' : 'border-(--color-success)/30 bg-(--color-success-subtle)/25 text-(--color-success)')}>
          {blockers.length > 0 ? `${blockers.length} blocker${blockers.length === 1 ? '' : 's'}` : warnings.length > 0 ? `${warnings.length} warning${warnings.length === 1 ? '' : 's'}` : 'Covered'}
        </span>
      </div>

      {unit.indexed_phase !== unit.phase && (
        <DetailSection title="Source-of-truth mismatch" Icon={Database} tone="warning">
          <div className="rounded-md border border-(--color-warning)/30 bg-(--color-warning-subtle)/20 px-2.5 py-2 text-xs text-(--color-text-2)">
            KB says <span className="font-mono text-(--color-text)">{unit.phase}</span>; the local index says <span className="font-mono text-(--color-text)">{unit.indexed_phase}</span>. Reindex before trusting index-backed dashboards.
          </div>
        </DetailSection>
      )}

      {unit.next_action && (
        <DetailSection title="Recommended next action" Icon={Play}>
          <div className={cn('rounded-md border px-2.5 py-2.5', unit.next_action.allowed ? 'border-(--color-success)/30 bg-(--color-success-subtle)/15' : 'border-(--color-warning)/30 bg-(--color-warning-subtle)/15')}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-medium text-(--color-text)">{pipelineLabel(unit.next_action.pipeline)}</p>
                <p className="mt-0.5 text-[10px] text-(--color-text-subtle)">Advance toward {unit.next_action.target_phase}</p>
              </div>
              <button
                type="button"
                onClick={() => onRunNext(unit)}
                className="flex h-7 shrink-0 items-center gap-1 rounded-md bg-(--bg-page) px-2 text-[10px] font-medium text-(--color-text) shadow-sm hover:bg-(--bg-key)"
              >
                <Play size={11} /> Open
              </button>
            </div>
            {unit.next_action.scope_units.length > 1 && (
              <p className="mt-2 rounded bg-(--bg-page)/70 px-2 py-1 text-[9px] text-(--color-text-muted)">
                This action includes {unit.next_action.scope_units.length} units: {unit.next_action.scope_units.join(' → ')}
              </p>
            )}
            {!unit.next_action.allowed && unit.next_action.blockers.length > 0 && (
              <ul className="mt-2 space-y-1 text-[10px] text-(--color-warning)">
                {unit.next_action.blockers.slice(0, 3).map((blocker) => <li key={blocker}>• {blocker}</li>)}
              </ul>
            )}
          </div>
        </DetailSection>
      )}

      {unit.issues.length > 0 && (
        <DetailSection title={`Diagnostics · ${unit.issues.length}`} Icon={ShieldAlert} tone={blockers.length > 0 ? 'blocker' : 'warning'}>
          <div className="space-y-1.5">
            {unit.issues.map((issue) => (
              <DiagnosticRow
                key={`${issue.code}:${issue.message}`}
                issue={issue}
                onOpenKb={onOpenKb}
                onRun={() => onRunNext(unit, issue.pipeline)}
              />
            ))}
          </div>
        </DetailSection>
      )}

      <DetailSection title="Artifacts" Icon={FileCheck2}>
        <div className="grid gap-1.5 sm:grid-cols-2">
          <ArtifactButton label="Unit documentation" path={unit.doc_path} Icon={FileText} onOpen={onOpenKb} />
          <ArtifactButton label="Target mapping" path={unit.mapping_path} Icon={Map} onOpen={onOpenKb} />
          <ArtifactButton label="Compare evidence" path={unit.passing_run_id ? `run:${unit.passing_run_id}` : null} Icon={FlaskConical} onOpen={() => onOpenRun(unit.passing_run_id)} />
          <div className="rounded-md border border-(--color-border) px-2.5 py-2">
            <p className="text-[9px] uppercase text-(--color-text-subtle)">Recorded runs</p>
            <p className="mt-1 font-mono text-xs text-(--color-text)">{unit.run_count}{unit.latest_verdict ? ` · ${unit.latest_verdict}` : ''}</p>
          </div>
        </div>
      </DetailSection>

      <DetailSection title={`Business rules · ${unit.rules.length}`} Icon={FileText}>
        {unit.rules.length === 0 ? <p className="text-xs text-(--color-text-subtle)">No rule documents linked to this unit.</p> : (
          <div className="space-y-1.5">
            {unit.rules.map((rule) => (
              <button key={rule.id} type="button" onClick={() => onOpenKb(rule.path)} className="flex w-full items-start justify-between gap-2 rounded-md border border-(--color-border) px-2.5 py-2 text-left hover:bg-(--bg-key)">
                <span className="min-w-0"><span className="block font-mono text-[10px] text-(--color-text)">{rule.id}</span><span className="mt-0.5 block truncate text-[10px] text-(--color-text-muted)">{rule.title}</span></span>
                <span className={cn('shrink-0 rounded px-1.5 py-0.5 text-[8px] uppercase', rule.status === 'confirmed' ? 'bg-(--color-success-subtle)/25 text-(--color-success)' : 'bg-(--color-warning-subtle)/25 text-(--color-warning)')}>{rule.status}</span>
              </button>
            ))}
          </div>
        )}
      </DetailSection>

      <DetailSection title="Dependencies" Icon={Waypoints}>
        {unit.depends_on.length === 0 ? <p className="text-xs text-(--color-text-subtle)">No dependencies declared.</p> : <div className="flex flex-wrap gap-1">{unit.depends_on.map((item) => <span key={item} className="rounded bg-(--bg-key) px-1.5 py-1 font-mono text-[9px] text-(--color-text-muted)">{item}</span>)}</div>}
      </DetailSection>

      <DetailSection title={`Downstream impact · ${unit.impact_count}`} Icon={Waypoints}>
        {unit.dependent_units.length === 0 ? <p className="text-xs text-(--color-text-subtle)">No direct dependents are declared.</p> : <div className="flex flex-wrap gap-1">{unit.dependent_units.map((item) => <span key={item} className="rounded bg-(--color-info-subtle)/20 px-1.5 py-1 font-mono text-[9px] text-(--color-info)">{item}</span>)}</div>}
      </DetailSection>

      {(unit.links.length > 0 || unit.target_paths.length > 0) && (
        <DetailSection title="Explicit links" Icon={Link2}>
          <div className="space-y-1.5">
            {unit.links.map((link) => <div key={link.id} className="rounded-md border border-(--color-border) px-2.5 py-2"><p className="text-[9px] font-medium uppercase text-(--color-text-subtle)">{link.kind}</p><p className="mt-1 break-all font-mono text-[9px] text-(--color-text-muted)">{link.from_ref} → {link.to_ref}</p>{link.note && <p className="mt-1 text-[10px] text-(--color-text-2)">{link.note}</p>}</div>)}
            {unit.target_paths.map((path) => <div key={path} className="rounded bg-(--bg-key) px-2 py-1.5 font-mono text-[9px] text-(--color-text-muted)">target:{path}</div>)}
          </div>
        </DetailSection>
      )}
    </div>
  )
}

function ArtifactButton({ label, path, Icon, onOpen }: { label: string; path: string | null; Icon: typeof FileText; onOpen: (path: string | null) => void }) {
  return (
    <button type="button" disabled={!path} onClick={() => onOpen(path)} className="flex min-w-0 items-center gap-2 rounded-md border border-(--color-border) px-2.5 py-2 text-left transition-colors hover:bg-(--bg-key) disabled:cursor-default disabled:opacity-45">
      <Icon size={13} className={path ? 'text-(--color-success)' : 'text-(--color-text-subtle)'} />
      <span className="min-w-0"><span className="block text-[10px] font-medium text-(--color-text-2)">{label}</span><span className="block truncate font-mono text-[8px] text-(--color-text-subtle)">{path ?? 'missing'}</span></span>
    </button>
  )
}

function DiagnosticRow({
  issue,
  onOpenKb,
  onRun,
}: {
  issue: AimTraceabilityIssue
  onOpenKb: (path: string | null) => void
  onRun: () => void
}) {
  const tone = issue.severity === 'blocker' ? 'error' : issue.severity === 'warning' ? 'warning' : 'info'
  const Icon = issue.severity === 'blocker' ? CircleX : issue.severity === 'warning' ? CircleAlert : CircleCheck
  return (
    <div className={cn('flex items-start gap-2 rounded-md border px-2.5 py-2', tone === 'error' && 'border-(--color-error)/25 bg-(--color-error-subtle)/20', tone === 'warning' && 'border-(--color-warning)/25 bg-(--color-warning-subtle)/20', tone === 'info' && 'border-(--color-border) bg-(--bg-key)/40')}>
      <Icon size={12} className={cn('mt-0.5 shrink-0', tone === 'error' && 'text-(--color-error)', tone === 'warning' && 'text-(--color-warning)', tone === 'info' && 'text-(--color-text-subtle)')} />
      <div className="min-w-0 flex-1">
        <p className="text-[10px] leading-4 text-(--color-text-2)">{issue.message}</p>
        {issue.related_units.length > 0 && <p className="mt-1 truncate font-mono text-[8px] text-(--color-text-subtle)">{issue.related_units.join(' → ')}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-0.5">
        {issue.path && <button type="button" onClick={() => onOpenKb(issue.path)} title="Open related KB artifact" className="flex h-6 w-6 items-center justify-center rounded text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"><FileText size={11} /></button>}
        {issue.pipeline && <button type="button" onClick={onRun} title={`Open ${pipelineLabel(issue.pipeline)}`} className="flex h-6 w-6 items-center justify-center rounded text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"><Play size={11} /></button>}
      </div>
    </div>
  )
}

function DetailSection({ title, Icon, tone, children }: { title: string; Icon: typeof FileText; tone?: 'warning' | 'blocker'; children: React.ReactNode }) {
  return (
    <section className="mt-5 border-t border-(--color-border) pt-3">
      <h3 className={cn('mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase text-(--color-text-subtle)', tone === 'warning' && 'text-(--color-warning)', tone === 'blocker' && 'text-(--color-error)')}><Icon size={11} />{title}</h3>
      {children}
    </section>
  )
}

function TraceabilitySkeleton() {
  return (
    <div className="h-full p-4" aria-label="Loading traceability">
      <div className="flex items-center justify-between gap-3"><Skeleton className="h-8 w-40" /><Skeleton className="h-8 w-72" /></div>
      <div className="mt-4 grid grid-cols-4 gap-2 lg:grid-cols-8">{Array.from({ length: 8 }, (_, index) => <Skeleton key={index} className="h-12" />)}</div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">{Array.from({ length: 10 }, (_, index) => <Skeleton key={index} className="h-14" />)}</div>
    </div>
  )
}