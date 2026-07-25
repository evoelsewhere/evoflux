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

import { useMemo, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  BookOpen,
  CircleAlert,
  CircleCheck,
  CirclePause,
  CircleX,
  FolderGit2,
  FolderInput,
  FolderOutput,
  LayoutGrid,
  Link2,
  List,
  LockKeyhole,
  Loader2,
  Play,
  Search,
  ShieldCheck,
  X,
} from 'lucide-react'
import {
  getAimProjectHealth,
  getAimProjectSummary,
  getAimCutoverChecklist,
  listAimApprovals,
  listAimRuns,
  listAimUnits,
  reconcileAimState,
  replyAskUserQuestion,
  updateAimCutoverChecklist,
} from '@/api/client'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { queryKeys } from '@/queries/keys'
import { useAimMetaQuery } from '@/queries/useAimMetaQuery'
import { resolveAimRoleWorkspaces } from '@/lib/aim-kb'
import { AimSidePanel } from '@/components/AimSidePanel'
import { setAimKbOpenPath, setAimPipelinePrefill } from '@/lib/aimHandoff'
import { Button } from '@/components/ui/button'
import { Combobox } from '@/components/ui/combobox'
import { cn } from '@/lib/utils'
import { formatApprovalQuestion } from '@/utils/approvalQuestion'
import { MarkdownBlock } from '@/utils/markdown'
import type {
  AimPhaseCounts,
  AimApproval,
  AimCutoverChecklist,
  AimRunListItem,
  AimUnitOut,
  CodingProject,
} from '@/api/types'

// Phase order + labels + phase→next-pipeline come from the backend
// (GET /aim/meta, via useAimMetaQuery). These fallbacks mirror the backend
// defaults so the board never flashes empty before the query resolves (or if
// the endpoint is briefly unavailable) — they are NOT a second source of
// truth.
const FALLBACK_PHASES = [
  'inventory',
  'understood',
  'designed',
  'converted',
  'equivalent',
  'cutover',
]

const FALLBACK_PHASE_LABELS: Record<string, string> = {
  inventory: 'Inventory',
  understood: 'Understood',
  designed: 'Designed',
  converted: 'Converted',
  equivalent: 'Equivalent',
  cutover: 'Cutover',
}

// Distribution-bar segment colors — purely a frontend styling decision
// (muted → accent → success as units progress), keyed by phase with a
// neutral fallback for any phase the backend adds that the UI hasn't styled.
const PHASE_BAR_CLASSES: Record<string, string> = {
  inventory: 'bg-(--color-text-subtle)/40',
  understood: 'bg-(--color-accent)/40',
  designed: 'bg-(--color-accent)/70',
  converted: 'bg-(--color-accent)',
  equivalent: 'bg-(--color-success)/70',
  cutover: 'bg-(--color-success)',
}
const barClass = (phase: string) => PHASE_BAR_CLASSES[phase] ?? 'bg-(--color-text-subtle)/40'

// Friendly button labels for the built-in pipelines; any other pipeline key
// (a rulebook-authored one) gets a title-cased fallback.
const PIPELINE_LABELS: Record<string, string> = {
  'aim-understand': 'Understand',
  'aim-design-unit': 'Design',
  'aim-convert-unit': 'Convert',
  'aim-convert-wave': 'Convert wave',
  'aim-test-compare': 'Test-compare',
  'aim-cutover-check': 'Cutover',
}
function pipelineLabel(key: string): string {
  return PIPELINE_LABELS[key] ?? key.replace(/^aim-/, '').replace(/-/g, ' ')
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
  const [viewMode, setViewMode] = useState<'queue' | 'flow'>('queue')
  const [queueFilter, setQueueFilter] = useState<'attention' | 'ready' | 'active' | 'all'>(
    'attention',
  )
  const [replyingApproval, setReplyingApproval] = useState<string | null>(null)
  const [approvalError, setApprovalError] = useState<string | null>(null)
  const approvalReplyRef = useRef<string | null>(null)
  const [reconcileOpen, setReconcileOpen] = useState(false)
  const [reconciling, setReconciling] = useState(false)
  const [reconcileError, setReconcileError] = useState<string | null>(null)
  const [cutoverWave, setCutoverWave] = useState<number | null>(null)
  const [cutoverChecklist, setCutoverChecklist] = useState<AimCutoverChecklist | null>(
    null,
  )
  const [cutoverLoading, setCutoverLoading] = useState(false)
  const [cutoverError, setCutoverError] = useState<string | null>(null)

  const summaryQuery = useQuery({
    queryKey: queryKeys.projects.aimSummary(project.id),
    queryFn: () => getAimProjectSummary(project.id),
    refetchInterval: 10_000,
  })

  const unitsQuery = useQuery({
    queryKey: queryKeys.projects.aimUnits(project.id, undefined),
    queryFn: () => listAimUnits(project.id),
    refetchInterval: 10_000,
  })

  const healthQuery = useQuery({
    queryKey: [...queryKeys.projects.detail(project.id), 'aim-health'],
    queryFn: () => getAimProjectHealth(project.id),
    refetchInterval: 15_000,
  })

  const approvalsQuery = useQuery({
    queryKey: [...queryKeys.projects.detail(project.id), 'aim-approvals'],
    queryFn: () => listAimApprovals(project.id),
    refetchInterval: 3_000,
  })

  const recentRunsQuery = useQuery({
    queryKey: [...queryKeys.projects.detail(project.id), 'aim-recent-runs'],
    queryFn: () => listAimRuns(project.id, 50),
    refetchInterval: 10_000,
  })
  const allRuns = useMemo(() => recentRunsQuery.data ?? [], [recentRunsQuery.data])

  const meta = useAimMetaQuery().data
  const phases = meta?.unit_phases ?? FALLBACK_PHASES
  const phaseLabels = meta?.phase_labels ?? FALLBACK_PHASE_LABELS

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
        (wave === 'all' || u.wave === wave) &&
        (moduleFilter === 'all' || u.module === moduleFilter) &&
        (!query || `${u.module}/${u.name}`.toLowerCase().includes(query)),
    )
  }, [units, wave, moduleFilter, search])

  const activeUnits = visibleUnits.filter((unit) => unit.claim !== null)
  const blockedUnits = visibleUnits.filter(
    (unit) =>
      !unit.state_verified ||
      (unit.next_action !== null && !unit.next_action.allowed && unit.claim === null),
  )
  const readyUnits = visibleUnits.filter(
    (unit) => unit.state_verified && unit.next_action?.allowed && unit.claim === null,
  )
  const queueUnits =
    queueFilter === 'attention'
      ? blockedUnits
      : queueFilter === 'ready'
        ? readyUnits
        : queueFilter === 'active'
          ? activeUnits
          : visibleUnits
  const healthProblems = (healthQuery.data?.checks ?? []).filter(
    (check) => check.status !== 'pass',
  )
  const hasLegacyState = healthQuery.data?.checks.some(
    (check) => check.id === 'kb' && check.message.includes('Legacy state schema'),
  )

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

  const replyApproval = async (approval: AimApproval, answer: string) => {
    if (approvalReplyRef.current !== null) return
    approvalReplyRef.current = approval.request_id
    setReplyingApproval(approval.request_id)
    setApprovalError(null)
    try {
      await replyAskUserQuestion(approval.session_id, approval.request_id, [answer])
      await approvalsQuery.refetch()
      void summaryQuery.refetch()
      void unitsQuery.refetch()
      void healthQuery.refetch()
    } catch (error) {
      setApprovalError(error instanceof Error ? error.message : 'Failed to answer approval.')
    } finally {
      approvalReplyRef.current = null
      setReplyingApproval(null)
    }
  }

  const reconcileLegacyState = async () => {
    setReconciling(true)
    setReconcileError(null)
    try {
      await reconcileAimState(project.id)
      await Promise.all([
        healthQuery.refetch(),
        unitsQuery.refetch(),
        summaryQuery.refetch(),
      ])
      setReconcileOpen(false)
    } catch (error) {
      setReconcileError(
        error instanceof Error ? error.message : 'Failed to reconcile legacy state.',
      )
    } finally {
      setReconciling(false)
    }
  }

  const openCutoverChecklist = async (selectedWave: number) => {
    setCutoverWave(selectedWave)
    setCutoverChecklist(null)
    setCutoverError(null)
    setCutoverLoading(true)
    try {
      setCutoverChecklist(await getAimCutoverChecklist(project.id, selectedWave))
    } catch (error) {
      setCutoverError(
        error instanceof Error ? error.message : 'Failed to load cutover checklist.',
      )
    } finally {
      setCutoverLoading(false)
    }
  }

  const saveCutoverChecklist = async () => {
    if (cutoverWave === null || !cutoverChecklist) return
    setCutoverLoading(true)
    setCutoverError(null)
    try {
      await updateAimCutoverChecklist(project.id, cutoverWave, {
        deployment_ready: cutoverChecklist.deployment_ready,
        data_reconciled: cutoverChecklist.data_reconciled,
        rollback_ready: cutoverChecklist.rollback_ready,
        monitoring_ready: cutoverChecklist.monitoring_ready,
        approved_by: cutoverChecklist.approved_by,
        notes: cutoverChecklist.notes,
      })
      await unitsQuery.refetch()
      setCutoverWave(null)
      setCutoverChecklist(null)
    } catch (error) {
      setCutoverError(
        error instanceof Error ? error.message : 'Failed to save cutover checklist.',
      )
    } finally {
      setCutoverLoading(false)
    }
  }

  return (
    <div className="flex h-full min-h-0">
      <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex flex-col items-stretch gap-2 border-b border-(--color-border) px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
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
            {healthQuery.data && (
              <span
                className={cn(
                  'rounded px-1.5 py-0.5 text-[10px] font-medium',
                  healthQuery.data.status === 'ready'
                    ? 'bg-(--color-success-bg,var(--bg-key)) text-(--color-success)'
                    : healthQuery.data.status === 'degraded'
                      ? 'bg-(--bg-key) text-(--color-warning,orange)'
                      : 'bg-(--color-error-subtle,var(--bg-key)) text-(--color-error)',
                )}
              >
                {healthQuery.data.status}
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-1.5 sm:flex sm:shrink-0 sm:items-center">
            {/* Unit search — client-side, composes with wave + module. */}
            {units.length > 0 && (
              <span className="relative col-span-2 sm:col-span-1">
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
                  className="w-full rounded bg-(--bg-key) py-1 pl-6 pr-2 text-xs text-(--color-text) placeholder:text-(--color-text-subtle) sm:w-36"
                />
              </span>
            )}
            {modules.length > 1 && (
              <Combobox
                size="sm"
                value={moduleFilter === 'all' ? null : moduleFilter}
                onValueChange={(v) => setModuleFilter(v ?? 'all')}
                items={[
                  { value: 'all', label: 'Module: all' },
                  ...modules.map((m) => ({ value: m, label: m })),
                ]}
                placeholder="Module: all"
                emptyText="No module matches."
                className="w-full sm:w-40"
              />
            )}
            {waves.length > 0 && (
              <select
                value={wave}
                onChange={(e) => setWave(e.target.value === 'all' ? 'all' : Number(e.target.value))}
                className="w-full rounded bg-(--bg-key) px-2 py-1 text-xs text-(--color-text) sm:w-auto"
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

        {healthProblems.length > 0 && (
          <div className="border-b border-(--color-border) bg-(--color-error-subtle,var(--bg-key)) px-4 py-2">
            <div className="flex items-start gap-2">
              <CircleAlert size={13} className="mt-0.5 shrink-0 text-(--color-error)" />
              <div className="min-w-0 flex-1">
                <p className="text-[11px] font-medium text-(--color-error)">
                  Project prerequisites need attention
                </p>
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5">
                  {healthProblems.slice(0, 5).map((check) => (
                    <span
                      key={check.id}
                      className={cn(
                        'text-[10px]',
                        check.status === 'fail'
                          ? 'text-(--color-error)'
                          : 'text-(--color-warning,orange)',
                      )}
                      title={check.message}
                    >
                      {check.label}: {check.message}
                    </span>
                  ))}
                </div>
              </div>
              {hasLegacyState && (
                <Button size="sm" variant="outline" onClick={() => setReconcileOpen(true)}>
                  Reconcile state
                </Button>
              )}
            </div>
          </div>
        )}

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

        <div className="grid shrink-0 grid-cols-2 gap-2 border-b border-(--color-border) p-3 sm:grid-cols-5">
          {summaryQuery.isLoading ? (
            <p className="col-span-5 text-xs text-(--color-text-subtle)">Loading summary…</p>
          ) : summaryQuery.isError ? (
            <p className="col-span-5 text-xs text-(--color-error)">Failed to load summary</p>
          ) : (
            <>
              <MetricCard label="Total units" value={totalUnits} />
              <MetricCard label="Ready next" value={readyUnits.length} tone="success" />
              <MetricCard label="Blocked" value={blockedUnits.length} tone="error" />
              <MetricCard label="Active claims" value={activeUnits.length} tone="accent" />
              <MetricCard
                label="Equivalent"
                value={`${summaryQuery.data?.equivalent_pct.toFixed(1) ?? '0.0'}%`}
              />
              {phaseCounts && totalUnits > 0 && (
                <div className="col-span-2 sm:col-span-5">
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

        {(approvalsQuery.data?.length ?? 0) > 0 && (
          <ApprovalInbox
            approvals={approvalsQuery.data ?? []}
            replyingId={replyingApproval}
            error={approvalError}
            onReply={(approval, answer) => void replyApproval(approval, answer)}
          />
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
              <Button size="sm" onClick={() => goRunPipeline('aim-assess')}>
                <Play size={12} />
                Run assess
              </Button>
            </div>
          ) : visibleUnits.length === 0 ? (
            <p className="text-xs text-(--color-text-subtle)">
              No units match the current filters.
            </p>
          ) : (
            <div className="space-y-3">
              <WaveControl
                units={visibleUnits}
                onConfigureCutover={(selectedWave) => void openCutoverChecklist(selectedWave)}
              />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="inline-flex rounded-md bg-(--bg-key) p-0.5">
                  {(
                    [
                      ['attention', `Attention ${blockedUnits.length}`],
                      ['ready', `Ready ${readyUnits.length}`],
                      ['active', `Active ${activeUnits.length}`],
                      ['all', `All ${visibleUnits.length}`],
                    ] as const
                  ).map(([key, label]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setQueueFilter(key)}
                      className={cn(
                        'rounded px-2 py-1 text-[11px] transition-colors',
                        queueFilter === key
                          ? 'bg-(--bg-page) font-medium text-(--color-text) shadow-sm'
                          : 'text-(--color-text-muted) hover:text-(--color-text)',
                      )}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <div className="inline-flex rounded-md border border-(--color-border) p-0.5">
                  <button
                    type="button"
                    onClick={() => setViewMode('queue')}
                    aria-label="Queue view"
                    title="Queue view"
                    className={cn(
                      'rounded p-1',
                      viewMode === 'queue'
                        ? 'bg-(--bg-key) text-(--color-accent)'
                        : 'text-(--color-text-subtle)',
                    )}
                  >
                    <List size={13} />
                  </button>
                  <button
                    type="button"
                    onClick={() => setViewMode('flow')}
                    aria-label="Flow view"
                    title="Flow view"
                    className={cn(
                      'rounded p-1',
                      viewMode === 'flow'
                        ? 'bg-(--bg-key) text-(--color-accent)'
                        : 'text-(--color-text-subtle)',
                    )}
                  >
                    <LayoutGrid size={13} />
                  </button>
                </div>
              </div>

              {viewMode === 'queue' ? (
                <UnitQueue
                  units={queueUnits}
                  selectedUnitId={selectedUnitId}
                  onSelect={(unit) =>
                    setSelectedUnitId(unit.id === selectedUnitId ? null : unit.id)
                  }
                />
              ) : (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                  {phases.map((phase) => {
                    const phaseUnits = visibleUnits.filter((unit) => unit.phase === phase)
                    return (
                      <div key={phase} className="min-w-0">
                        <p className="mb-1.5 truncate text-[11px] text-(--color-text-subtle)">
                          {phaseLabels[phase] ?? phase} · {phaseUnits.length}
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

      {reconcileOpen && (
        <div
          className="fixed inset-0 z-(--z-modal) flex items-center justify-center bg-(--color-overlay) p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="aim-reconcile-title"
        >
          <div className="w-full max-w-md rounded-md border border-(--color-border) bg-(--bg-card) p-5 shadow-xl">
            <h2 id="aim-reconcile-title" className="text-sm font-semibold text-(--color-text)">
              Accept current state as baseline?
            </h2>
            <p className="mt-2 text-xs leading-5 text-(--color-text-muted)">
              AIM will not invent missing history. It will write a reconciliation audit file and
              one baseline transition event for every unit already beyond Inventory, then enable
              schema-v2 lifecycle checks.
            </p>
            {reconcileError && (
              <p className="mt-2 text-xs text-(--color-error)">{reconcileError}</p>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={reconciling}
                onClick={() => setReconcileOpen(false)}
              >
                Cancel
              </Button>
              <Button size="sm" disabled={reconciling} onClick={() => void reconcileLegacyState()}>
                {reconciling && <Loader2 size={11} className="animate-spin" />}
                Accept baseline
              </Button>
            </div>
          </div>
        </div>
      )}
      {cutoverWave !== null && (
        <div
          className="fixed inset-0 z-(--z-modal) flex items-center justify-center bg-(--color-overlay) p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="aim-cutover-title"
        >
          <div className="w-full max-w-md rounded-md border border-(--color-border) bg-(--bg-card) p-5 shadow-xl">
            <h2 id="aim-cutover-title" className="text-sm font-semibold text-(--color-text)">
              Wave {cutoverWave} cutover readiness
            </h2>
            {cutoverLoading && !cutoverChecklist ? (
              <p className="mt-4 flex items-center gap-1.5 text-xs text-(--color-text-muted)">
                <Loader2 size={12} className="animate-spin" /> Loading checklist…
              </p>
            ) : cutoverChecklist ? (
              <div className="mt-3 space-y-3">
                {(
                  [
                    ['deployment_ready', 'Deployment plan and artifacts are ready'],
                    ['data_reconciled', 'Data migration/reconciliation is complete'],
                    ['rollback_ready', 'Rollback plan is tested and owned'],
                    ['monitoring_ready', 'Monitoring and hypercare are ready'],
                  ] as const
                ).map(([field, label]) => (
                  <label key={field} className="flex items-start gap-2 text-xs text-(--color-text-2)">
                    <input
                      type="checkbox"
                      checked={cutoverChecklist[field]}
                      onChange={(event) =>
                        setCutoverChecklist((current) =>
                          current ? { ...current, [field]: event.target.checked } : current,
                        )
                      }
                      className="mt-0.5 h-3.5 w-3.5"
                    />
                    {label}
                  </label>
                ))}
                <label className="block text-xs text-(--color-text-muted)">
                  Approved by
                  <input
                    value={cutoverChecklist.approved_by ?? ''}
                    onChange={(event) =>
                      setCutoverChecklist((current) =>
                        current ? { ...current, approved_by: event.target.value } : current,
                      )
                    }
                    className="mt-1 w-full rounded-md border border-(--color-border) bg-(--bg-subtle) px-2.5 py-1.5 text-xs text-(--color-text)"
                    placeholder="Release manager / change record"
                  />
                </label>
                <label className="block text-xs text-(--color-text-muted)">
                  Notes
                  <textarea
                    value={cutoverChecklist.notes}
                    onChange={(event) =>
                      setCutoverChecklist((current) =>
                        current ? { ...current, notes: event.target.value } : current,
                      )
                    }
                    rows={3}
                    className="mt-1 w-full resize-none rounded-md border border-(--color-border) bg-(--bg-subtle) px-2.5 py-1.5 text-xs text-(--color-text)"
                  />
                </label>
              </div>
            ) : null}
            {cutoverError && <p className="mt-2 text-xs text-(--color-error)">{cutoverError}</p>}
            <div className="mt-4 flex justify-end gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={cutoverLoading}
                onClick={() => {
                  setCutoverWave(null)
                  setCutoverChecklist(null)
                }}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                disabled={cutoverLoading || !cutoverChecklist}
                onClick={() => void saveCutoverChecklist()}
              >
                {cutoverLoading && <Loader2 size={11} className="animate-spin" />}
                Save checklist
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function ApprovalInbox({
  approvals,
  replyingId,
  error,
  onReply,
}: {
  approvals: AimApproval[]
  replyingId: string | null
  error: string | null
  onReply: (approval: AimApproval, answer: string) => void
}) {
  return (
    <div className="border-b border-(--color-border) bg-(--bg-key)/60 px-4 py-2.5">
      <div className="mb-1.5 flex items-center gap-1.5">
        <CirclePause size={12} className="text-(--color-warning,orange)" />
        <p className="text-[10px] font-semibold uppercase text-(--color-text-subtle)">
          Approval inbox · {approvals.length}
        </p>
      </div>
      <div className="space-y-1.5">
        {approvals.map((approval) => (
          <div
            key={`${approval.execution_id}:${approval.request_id}`}
            className="flex flex-wrap items-start gap-2 rounded-md border border-(--color-border) bg-(--bg-page) px-3 py-2"
          >
            <div className="min-w-0 flex-1 basis-[40rem]">
              <p className="truncate text-xs font-medium text-(--color-text)">
                {approval.session_title ?? approval.workflow}
              </p>
              <div className="mt-1 max-h-48 overflow-auto pr-1 text-[11px] leading-4 text-(--color-text-muted) [&_h1]:text-xs [&_h2]:text-xs [&_h3]:text-[11px] [&_li]:my-0 [&_ol]:my-1 [&_p]:my-1 [&_pre]:my-1 [&_table]:my-1 [&_table]:text-[10px] [&_ul]:my-1">
                <MarkdownBlock
                  content={formatApprovalQuestion(approval.question)}
                  sessionId={approval.session_id}
                />
              </div>
            </div>
            <div className="flex shrink-0 gap-1">
              {approval.options.map((option) => (
                <Button
                  key={option}
                  size="sm"
                  variant={option.match(/approve|certify|cutover/i) ? 'default' : 'outline'}
                  disabled={replyingId !== null}
                  onClick={() => onReply(approval, option)}
                >
                  {replyingId === approval.request_id ? (
                    <Loader2 size={11} className="animate-spin" />
                  ) : null}
                  {option}
                </Button>
              ))}
            </div>
          </div>
        ))}
      </div>
      {error && <p className="mt-1.5 text-[11px] text-(--color-error)">{error}</p>}
    </div>
  )
}

function WaveControl({
  units,
  onConfigureCutover,
}: {
  units: AimUnitOut[]
  onConfigureCutover: (wave: number) => void
}) {
  const waves = [...new Set(units.map((unit) => unit.wave))].sort((left, right) => {
    if (left === null) return 1
    if (right === null) return -1
    return left - right
  })
  return (
    <div className="overflow-hidden rounded-md border border-(--color-border)">
      <div className="grid grid-cols-[4rem_1fr_3rem_3rem] gap-2 bg-(--bg-key) px-3 py-1.5 text-[10px] font-semibold uppercase text-(--color-text-subtle) sm:grid-cols-[5rem_1fr_4rem_4rem_4rem]">
        <span>Wave</span>
        <span>Progress</span>
        <span className="text-right">Ready</span>
        <span className="text-right">Blocked</span>
        <span className="hidden text-right sm:block">Active</span>
      </div>
      {waves.map((wave) => {
        const waveUnits = units.filter((unit) => unit.wave === wave)
        const complete = waveUnits.filter((unit) =>
          ['equivalent', 'cutover'].includes(unit.phase),
        ).length
        const ready = waveUnits.filter(
          (unit) => unit.next_action?.allowed && unit.claim === null,
        ).length
        const blocked = waveUnits.filter(
          (unit) => !unit.state_verified || (unit.next_action && !unit.next_action.allowed),
        ).length
        const active = waveUnits.filter((unit) => unit.claim !== null).length
        const pct = waveUnits.length > 0 ? (complete / waveUnits.length) * 100 : 0
        return (
          <div
            key={wave ?? 'unassigned'}
            className="grid grid-cols-[4rem_1fr_3rem_3rem] items-center gap-2 border-t border-(--color-border) px-3 py-2 text-xs sm:grid-cols-[5rem_1fr_4rem_4rem_4rem]"
          >
            <span className="flex items-center gap-1 font-medium text-(--color-text)">
              {wave === null ? 'Unassigned' : `Wave ${wave}`}
              {wave !== null && (
                <button
                  type="button"
                  onClick={() => onConfigureCutover(wave)}
                  aria-label={`Configure wave ${wave} cutover readiness`}
                  title="Cutover readiness checklist"
                  className="rounded p-0.5 text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-accent)"
                >
                  <ShieldCheck size={11} />
                </button>
              )}
            </span>
            <div className="flex items-center gap-2">
              <div className="h-1.5 min-w-16 flex-1 overflow-hidden rounded-full bg-(--bg-key)">
                <div className="h-full bg-(--color-success)" style={{ width: `${pct}%` }} />
              </div>
              <span className="w-14 shrink-0 text-[10px] text-(--color-text-subtle)">
                {complete}/{waveUnits.length}
              </span>
            </div>
            <span className="text-right text-(--color-success)">{ready}</span>
            <span className="text-right text-(--color-error)">{blocked}</span>
            <span className="hidden text-right text-(--color-accent) sm:block">{active}</span>
          </div>
        )
      })}
    </div>
  )
}

function UnitQueue({
  units,
  selectedUnitId,
  onSelect,
}: {
  units: AimUnitOut[]
  selectedUnitId: string | null
  onSelect: (unit: AimUnitOut) => void
}) {
  if (units.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-(--color-border) px-3 py-8 text-center text-xs text-(--color-text-subtle)">
        No units in this queue.
      </div>
    )
  }
  return (
    <div className="overflow-hidden rounded-md border border-(--color-border)">
      <div className="hidden grid-cols-[minmax(12rem,1.5fr)_7rem_4rem_minmax(10rem,1fr)_8rem] gap-3 bg-(--bg-key) px-3 py-1.5 text-[10px] font-semibold uppercase text-(--color-text-subtle) md:grid">
        <span>Unit</span>
        <span>Phase</span>
        <span>Wave</span>
        <span>Next action / blocker</span>
        <span>Ownership</span>
      </div>
      {units.map((unit) => {
        const firstBlocker = unit.state_error ?? unit.next_action?.blockers[0]
        return (
          <button
            key={unit.id}
            type="button"
            onClick={() => onSelect(unit)}
            className={cn(
              'grid w-full gap-1 border-t border-(--color-border) px-3 py-2 text-left transition-colors first:border-t-0 hover:bg-(--bg-key) md:grid-cols-[minmax(12rem,1.5fr)_7rem_4rem_minmax(10rem,1fr)_8rem] md:items-center md:gap-3',
              selectedUnitId === unit.id && 'bg-(--bg-key)',
            )}
          >
            <span className="min-w-0">
              <span className="block truncate font-mono text-xs text-(--color-text)">
                {unit.module}/{unit.name}
              </span>
              <span className="text-[10px] text-(--color-text-subtle)">
                {unit.kind} · rev {unit.revision}
              </span>
            </span>
            <span className="font-mono text-[11px] text-(--color-text-2)">{unit.phase}</span>
            <span className="text-[11px] text-(--color-text-muted)">{unit.wave ?? '—'}</span>
            <span className="min-w-0 text-[11px]">
              {unit.claim ? (
                <span className="text-(--color-accent)">Workflow in progress</span>
              ) : firstBlocker ? (
                <span className="block truncate text-(--color-error)" title={firstBlocker}>
                  {firstBlocker}
                </span>
              ) : unit.next_action ? (
                <span className="text-(--color-success)">
                  Ready: {pipelineLabel(unit.next_action.pipeline)}
                </span>
              ) : (
                <span className="text-(--color-text-subtle)">Lifecycle complete</span>
              )}
            </span>
            <span className="flex items-center gap-1 text-[10px] text-(--color-text-subtle)">
              {unit.claim ? (
                <>
                  <LockKeyhole size={10} className="text-(--color-accent)" />
                  <span className="truncate">{unit.claim.workflow_name.replace(/^aim-/, '')}</span>
                </>
              ) : unit.assignee ? (
                <span className="truncate">{unit.assignee}</span>
              ) : (
                'Unclaimed'
              )}
            </span>
          </button>
        )
      })}
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
  const next = unit.next_action
    ? { key: unit.next_action.pipeline, label: pipelineLabel(unit.next_action.pipeline) }
    : null
  const complexityEntries = Object.entries(unit.complexity).filter(
    ([, value]) => typeof value === 'string' || typeof value === 'number',
  )

  return (
    <AimSidePanel storageKey={STORAGE_KEYS.panels.aimUnitDetail} defaultWidth={320} minWidth={280} maxWidth={560}>
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-(--color-border) px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-(--color-text)">Unit</h2>
          <p className="mt-0.5 truncate font-mono text-xs text-(--color-text-subtle)">{unitKey}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close unit details"
          title="Close"
          className="rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
        >
          <X size={16} />
        </button>
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {/* Quick actions — pre-filled pipeline runs; the likely next step leads.
            A terminal phase (e.g. cutover) has no next pipeline. */}
        <div className="flex flex-wrap items-center gap-1.5">
          {next && (
            <Button
              size="sm"
              onClick={() => onRunPipeline(next.key, unit)}
              disabled={!unit.next_action?.allowed}
              title={unit.next_action?.blockers.join('\n') || undefined}
            >
              <Play size={11} />
              {next.label}
            </Button>
          )}
          {unit.kb_doc_path && (
            <Button size="sm" variant="secondary" onClick={() => onOpenKbDoc(unit)}>
              <BookOpen size={11} />
              KB doc
            </Button>
          )}
        </div>

        {unit.next_action && !unit.next_action.allowed && (
          <div className="rounded-md bg-(--color-error-subtle,var(--bg-key)) px-3 py-2 text-[11px] text-(--color-error)">
            <p className="font-medium">Next action blocked</p>
            {unit.next_action.blockers.map((blocker) => (
              <p key={blocker} className="mt-0.5">
                {blocker}
              </p>
            ))}
          </div>
        )}

        <div className="space-y-1.5 rounded-md bg-(--bg-key) px-3 py-2">
          <DetailRow label="Phase">
            <span className="font-mono">{unit.phase}</span>
          </DetailRow>
          <DetailRow label="Kind">{unit.kind}</DetailRow>
          <DetailRow label="Wave">{unit.wave ?? '—'}</DetailRow>
          <DetailRow label="Assignee">{unit.assignee ?? '—'}</DetailRow>
          <DetailRow label="Revision">{unit.revision}</DetailRow>
          <DetailRow label="Integrity">
            <span className={unit.state_verified ? 'text-(--color-success)' : 'text-(--color-error)'}>
              {unit.state_verified ? 'verified' : unit.state_error || 'unverified'}
            </span>
          </DetailRow>
          {unit.claim && (
            <DetailRow label="Active claim">
              {unit.claim.workflow_name} · until{' '}
              {new Date(unit.claim.lease_expires_at).toLocaleTimeString()}
            </DetailRow>
          )}
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
    </AimSidePanel>
  )
}

function PhaseBar({ counts, total }: { counts: AimPhaseCounts; total: number }) {
  const meta = useAimMetaQuery().data
  const phases = meta?.unit_phases ?? FALLBACK_PHASES
  const phaseLabels = meta?.phase_labels ?? FALLBACK_PHASE_LABELS
  const countOf = (phase: string) =>
    (counts as unknown as Record<string, number>)[phase] ?? 0
  return (
    <div>
      <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-(--bg-key)">
        {phases.map((phase) => {
          const count = countOf(phase)
          if (!count) return null
          return (
            <div
              key={phase}
              className={barClass(phase)}
              style={{ width: `${(count / total) * 100}%` }}
              title={`${phaseLabels[phase] ?? phase}: ${count}`}
            />
          )
        })}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
        {phases.map((phase) => (
          <span key={phase} className="flex items-center gap-1 text-[10px] text-(--color-text-subtle)">
            <span className={cn('h-1.5 w-1.5 rounded-full', barClass(phase))} />
            {phaseLabels[phase] ?? phase} {countOf(phase)}
          </span>
        ))}
      </div>
    </div>
  )
}

function MetricCard({
  label,
  value,
  tone = 'default',
}: {
  label: string
  value: string | number
  tone?: 'default' | 'success' | 'error' | 'accent'
}) {
  const valueTone =
    tone === 'success'
      ? 'text-(--color-success)'
      : tone === 'error'
        ? 'text-(--color-error)'
        : tone === 'accent'
          ? 'text-(--color-accent)'
          : 'text-(--color-text)'
  return (
    <div className="rounded bg-(--bg-key) px-3 py-2">
      <p className="text-[10px] text-(--color-text-subtle)">{label}</p>
      <p className={cn('text-base font-medium', valueTone)}>{value}</p>
    </div>
  )
}
