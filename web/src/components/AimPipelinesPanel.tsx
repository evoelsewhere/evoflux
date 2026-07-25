/**
 * AimPipelinesPanel — trigger the AIM workflow library with plain UI and
 * watch run status (aim-mode-shell-ux-spec.md v2.2 §3.3/§5.2 + AIM-4).
 *
 * Since AIM-4 the Run button executes the REAL workflow definitions
 * (POST /api/workflows/{name}/run against a fresh per-run session) — same
 * execution substrate as the composer's /workflow, no second path.
 *
 * The run table joins each per-run session with its workflow execution
 * (GET /workflows/executions?session_ids=) so rows show the real outcome
 * (● running / ⏸ needs input / ✓ pass / ✗ fail / ◼ stopped), and every row
 * opens a Run Monitor side panel: the execution's node-by-node progress,
 * per-node debug output (the "log"), an inline gate answerer while the
 * workflow is waiting, and a Stop button. None of that is chat — post-run
 * Discussion stays the mode's only chat entry point.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Bell,
  Bot,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CirclePause,
  CircleX,
  CornerDownLeft,
  FileText,
  Loader2,
  Maximize2,
  MessageSquareText,
  Minus,
  OctagonX,
  Play,
  Plus,
  Repeat,
  ShieldCheck,
  Shuffle,
  Wrench,
  X,
} from 'lucide-react'
import {
  approveWorkflow,
  getAimReadiness,
  getAimRun,
  getExecution,
  getPendingQuestions,
  getWorkflow,
  listAimRuns,
  listAimUnits,
  listTeamSessions,
  listWorkflowExecutions,
  replyAskUserQuestion,
  resolveTeamSession,
  runWorkflow,
  stopExecution,
  teamHistory,
  updateTeamSessionTitle,
} from '@/api/client'
import { queryKeys } from '@/queries/keys'
import { useWorkflowsQuery } from '@/queries/useWorkflowsQuery'
import { resolveAimRolePath } from '@/lib/aim-kb'
import { AimSidePanel } from '@/components/AimSidePanel'
import { Button } from '@/components/ui/button'
import { Combobox } from '@/components/ui/combobox'
import { TeamChatView } from '@/components/TeamChatView'
import { MarkdownBlock } from '@/utils/markdown'
import { formatApprovalQuestion } from '@/utils/approvalQuestion'
import { formatRelativeDate } from '@/utils/format'
import { takeAimPipelinePrefill } from '@/lib/aimHandoff'
import { cn } from '@/lib/utils'
import type {
  AimRunListItem,
  AimReadiness,
  CodingProject,
  MessageResponse,
  SessionResponse,
  WorkflowExecutionSummary,
  WorkflowInputSpec,
  WorkflowListItem,
  WorkflowNodeRun,
} from '@/api/types'

// §9.3: pipelines that write to the target repo — require confirm before run.
// A hand-maintained set of the two builtin pipelines known to do this; a
// rulebook-authored custom pipeline that also writes to target doesn't get
// this extra confirm (no generic "does this write to target" signal exists
// yet) — EvoFlux's own tool-permission gating still applies underneath.
const CONVERT_WORKFLOW_NAMES = new Set(['aim-convert-unit', 'aim-convert-wave'])

/** "aim-convert-unit" -> "Convert Unit" — used for the picker and anywhere
 * else a short display name reads better than the raw workflow name. The
 * full explanation lives in the workflow's own `description`, shown
 * separately in PipelineInfoCard. */
function pipelineDisplayName(workflowName: string): string {
  return workflowName
    .replace(/^aim-/, '')
    .split('-')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

/** One trigger-form field for a workflow's own declared input — renders
 * identically whether the workflow is one of the 6 builtin pipelines or a
 * rulebook-authored custom one. `unit` is the one name-based special case
 * (a Combobox sourced from real KB units instead of a bare text field);
 * everything else renders generically from its declared `type`. */
function WorkflowInputField({
  spec,
  value,
  onChange,
  unitOptions,
  waveOptions,
}: {
  spec: WorkflowInputSpec
  value: unknown
  onChange: (value: unknown) => void
  unitOptions: { key: string; phase: string; kind: string; wave: number | null }[]
  waveOptions: { wave: number; count: number }[]
}) {
  const label = spec.name
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')

  if (spec.name === 'unit') {
    return (
      <label className="flex min-w-52 flex-col gap-1 text-xs text-(--color-text-muted)">
        {label}
        {unitOptions.length > 0 ? (
          <Combobox
            size="sm"
            value={(value as string) || null}
            onValueChange={(v) => onChange(v ?? '')}
            items={unitOptions.map((unit) => ({
              value: unit.key,
              label: unit.key,
              meta: unit.phase,
              description: `${unit.kind}${unit.wave === null ? '' : ` · wave ${unit.wave}`}`,
              keywords: `${unit.kind} ${unit.phase} ${unit.wave ?? ''}`,
            }))}
            placeholder="Select a unit…"
            emptyText="No unit matches."
            ariaLabel={label}
            searchPlaceholder="Search units…"
            className="w-60"
          />
        ) : (
          <input
            type="text"
            value={(value as string) ?? ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder="module/UNIT (run assess first)"
            className="rounded-md border border-(--color-border) bg-(--bg-subtle) px-2 py-1.5 text-xs text-(--color-text) placeholder:text-(--color-text-muted)"
          />
        )}
      </label>
    )
  }

  if (spec.name === 'wave' && waveOptions.length > 0) {
    const selectedWave =
      value !== undefined && value !== null && value !== '' ? String(value) : null
    return (
      <label className="flex w-32 flex-col gap-1 text-xs text-(--color-text-muted)">
        {label}
        <Combobox
          size="sm"
          value={selectedWave}
          onValueChange={(selected) => onChange(selected ?? '')}
          items={waveOptions.map((option) => ({
            value: String(option.wave),
            label: `Wave ${option.wave}`,
            meta: `${option.count} units`,
            keywords: `${option.wave} ${option.count}`,
          }))}
          placeholder="Select wave…"
          emptyText="No wave matches."
          ariaLabel={label}
          searchPlaceholder="Search waves…"
        />
      </label>
    )
  }

  if (spec.type === 'enum') {
    const options = spec.options ?? []
    return (
      <label className="flex min-w-32 flex-col gap-1 text-xs text-(--color-text-muted)">
        {label}
        <Combobox
          size="sm"
          value={typeof value === 'string' && value ? value : null}
          onValueChange={(selected) => onChange(selected ?? '')}
          items={options.map((option) => ({
            value: option,
            label: option
              .split(/[-_]/)
              .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
              .join(' '),
            meta: option,
          }))}
          placeholder={`Select ${label.toLocaleLowerCase()}…`}
          emptyText={`No ${label.toLocaleLowerCase()} matches.`}
          ariaLabel={label}
          searchPlaceholder={`Search ${label.toLocaleLowerCase()}…`}
        />
      </label>
    )
  }

  if (spec.type === 'boolean') {
    return (
      <label className="flex flex-col gap-1 text-xs text-(--color-text-muted)">
        {label}
        <span className="flex h-[30px] items-center">
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(e) => onChange(e.target.checked)}
            className="h-3.5 w-3.5 rounded border-(--color-border)"
          />
        </span>
      </label>
    )
  }

  return (
    <label
      className={cn(
        'flex flex-col gap-1 text-xs text-(--color-text-muted)',
        spec.type === 'number' ? 'w-24' : 'min-w-32',
      )}
    >
      {label}
      <input
        type={spec.type === 'number' ? 'number' : 'text'}
        value={(value as string) ?? ''}
        onChange={(e) => onChange(e.target.value)}
        placeholder={spec.description || undefined}
        className="rounded-md border border-(--color-border) bg-(--bg-subtle) px-2 py-1.5 text-xs text-(--color-text) placeholder:text-(--color-text-muted)"
      />
    </label>
  )
}

/** Row status once session + execution are joined. `interrupted` = the DB
 * says running but no stream is live (backend restarted mid-run). */
type RunDisplayStatus =
  | 'running'
  | 'waiting_gate'
  | 'completed'
  | 'failed'
  | 'stopped'
  | 'interrupted'
  | 'done'

/** Wall-clock of a run, compact: "34s", "12m 05s", "1h 22m". Live runs
 * show elapsed-so-far (refreshed by the 5s poll re-render). */
function executionDuration(execution: WorkflowExecutionSummary | undefined): string {
  if (!execution) return '—'
  const start = new Date(execution.started_at).getTime()
  const end = execution.ended_at ? new Date(execution.ended_at).getTime() : Date.now()
  const totalSeconds = Math.max(0, Math.round((end - start) / 1000))
  if (totalSeconds < 60) return `${totalSeconds}s`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes < 60) return `${minutes}m ${String(seconds).padStart(2, '0')}s`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ${String(minutes % 60).padStart(2, '0')}m`
}

function displayStatus(
  sessionRunning: boolean,
  execution: WorkflowExecutionSummary | undefined,
): RunDisplayStatus {
  if (!execution) return sessionRunning ? 'running' : 'done'
  if (execution.status === 'running' || execution.status === 'waiting_gate') {
    // `live` comes straight from the in-memory runner — the one truthful
    // liveness source. The session's streaming flag can't be used here:
    // pipelines whose nodes never open a chat turn (e.g. cutover-check is
    // all tool/gate nodes) never read as "running" on the sessions list.
    return execution.live ? (execution.status as RunDisplayStatus) : 'interrupted'
  }
  return execution.status as RunDisplayStatus
}

export function AimPipelinesPanel({
  project,
  runId,
}: {
  project: CodingProject
  /** Deep-link from Overview's recent-runs strip or a shared
   * /aim/$projectId/runs/$runId URL — opens that run's Report panel. */
  runId?: string
}) {
  const queryClient = useQueryClient()
  const targetWorkspace = resolveAimRolePath(project, 'target')
  // A unit card's quick action lands here with the form pre-filled —
  // consumed once, then this screen behaves as if hand-opened.
  const [prefill] = useState(() => takeAimPipelinePrefill())

  // The pipeline picker is every discovered scope="aim" workflow. Project
  // rulebooks never install or mutate workflows in the global discovery root.
  const workflowsQ = useWorkflowsQuery(targetWorkspace)
  const aimWorkflows = useMemo(
    () =>
      (workflowsQ.data?.workflows ?? [])
        .filter((wf) => wf.scope === 'aim')
        .sort((a, b) => a.name.localeCompare(b.name)),
    [workflowsQ.data],
  )
  const workflowByName = useMemo(
    () => new Map(aimWorkflows.map((wf) => [wf.name, wf])),
    [aimWorkflows],
  )

  const [pipelineName, setPipelineName] = useState<string | null>(
    () => prefill?.pipeline ?? null,
  )
  // Default to the first discovered workflow (alphabetically, "aim-assess"
  // sorts first) once the list is known, if the current selection — the
  // prefill's name, or nothing yet — doesn't match a real one.
  useEffect(() => {
    if (aimWorkflows.length === 0) return
    if (pipelineName && aimWorkflows.some((wf) => wf.name === pipelineName)) return
    setPipelineName(aimWorkflows[0].name)
  }, [aimWorkflows, pipelineName])

  const selectedWorkflow = pipelineName ? workflowByName.get(pipelineName) : undefined

  // One generic value bag keyed by each workflow's own declared input
  // name — replaces separate unit/wave/case_set state so any custom
  // pipeline's inputs render and submit correctly, not just the 6 known
  // shapes. Seeded from the prefill regardless of which pipeline ends up
  // selected; a key with no matching input on the current workflow is
  // simply unused.
  const [inputValuesByPipeline, setInputValuesByPipeline] = useState<
    Record<string, Record<string, unknown>>
  >(() =>
    prefill?.pipeline
      ? {
          [prefill.pipeline]: {
            unit: prefill.unit ?? '',
            wave: prefill.wave != null ? String(prefill.wave) : '',
          },
        }
      : {},
  )
  const inputValues = useMemo(() => {
    const values = pipelineName ? { ...(inputValuesByPipeline[pipelineName] ?? {}) } : {}
    for (const spec of selectedWorkflow?.inputs ?? []) {
      if (values[spec.name] !== undefined) continue
      if (spec.default !== undefined) values[spec.name] = spec.default
      else if (spec.type === 'enum') values[spec.name] = spec.options?.[0] ?? ''
      else if (spec.type === 'boolean') values[spec.name] = false
      else values[spec.name] = ''
    }
    return values
  }, [inputValuesByPipeline, pipelineName, selectedWorkflow])
  const setInputValue = useCallback((name: string, value: unknown) => {
    if (!pipelineName) return
    setInputValuesByPipeline((previous) => ({
      ...previous,
      [pipelineName]: {
        ...(previous[pipelineName] ?? {}),
        [name]: value,
      },
    }))
  }, [pipelineName])

  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [runHistoryCollapsed, setRunHistoryCollapsed] = useState(false)
  // §9.3: convert pipelines write to the target repo — confirm before run.
  const [confirmOpen, setConfirmOpen] = useState(false)
  // The one chat surface in the whole mode: a finished run's transcript.
  // Narrowed for the same reason as monitorSession — Discussion (below)
  // only ever reads id/title/workspace, and opening it from a Monitor
  // panel that resolved a session outside the current table page (a
  // report-originated deep link) doesn't have a full SessionResponse.
  const [discussion, setDiscussion] = useState<Pick<
    SessionResponse,
    'id' | 'title' | 'workspace'
  > | null>(null)
  // Run Monitor: node progress + log + inline gate for one run's session.
  // Narrowed to what RunMonitorPanel actually needs (not the full
  // SessionResponse) so opening it from the Report panel — which only
  // knows a session_id, not a table row — doesn't need a fake object;
  // RunMonitorPanel resolves its own execution from sessionId alone.
  const [monitorSession, setMonitorSession] = useState<Pick<
    SessionResponse,
    'id' | 'title' | 'running'
  > | null>(null)
  // Report: the aim_runs verdict + stats + JSON report for a run that has
  // one (Runs & Reports folded in here — see ReportPanel below).
  const [reportRun, setReportRun] = useState<{ runId: string; title?: string } | null>(null)

  // Deep-link: open the report panel for the linked run, once per runId.
  useEffect(() => {
    if (!runId) return
    setMonitorSession(null)
    setDiscussion(null)
    setReportRun({ runId })
  }, [runId])

  const unitsQuery = useQuery({
    queryKey: queryKeys.projects.aimUnits(project.id, undefined),
    queryFn: () => listAimUnits(project.id),
    staleTime: 30_000,
  })
  const units = useMemo(() => unitsQuery.data ?? [], [unitsQuery.data])
  const unitOptions = useMemo(
    () =>
      units
        .map((u) => ({
          key: `${u.module}/${u.name}`,
          phase: u.phase,
          kind: u.kind,
          wave: u.wave,
        }))
        .sort((a, b) => a.key.localeCompare(b.key)),
    [units],
  )
  const waveOptions = useMemo(() => {
    const counts = new Map<number, number>()
    for (const unit of units) {
      if (unit.wave === null) continue
      counts.set(unit.wave, (counts.get(unit.wave) ?? 0) + 1)
    }
    return [...counts.entries()]
      .sort(([left], [right]) => left - right)
      .map(([wave, count]) => ({ wave, count }))
  }, [units])

  const readinessInputs = useMemo(() => {
    const unit = typeof inputValues.unit === 'string' ? inputValues.unit.trim() : undefined
    const waveRaw = inputValues.wave
    const wave =
      waveRaw !== undefined && waveRaw !== '' && !Number.isNaN(Number(waveRaw))
        ? Number(waveRaw)
        : undefined
    const caseSet =
      typeof inputValues.case_set === 'string' ? inputValues.case_set.trim() : undefined
    const overwrite =
      typeof inputValues.overwrite === 'boolean' ? inputValues.overwrite : undefined
    return { unit: unit || undefined, wave, case_set: caseSet || undefined, overwrite }
  }, [inputValues])

  const requiredInputsPresent = (selectedWorkflow?.inputs ?? []).every((spec) => {
    if (!spec.required) return true
    const value = inputValues[spec.name]
    return value !== undefined && value !== null && value !== ''
  })

  const readinessQuery = useQuery({
    queryKey: [
      'aim-pipeline-readiness',
      project.id,
      selectedWorkflow?.name ?? '',
      readinessInputs,
    ],
    queryFn: () =>
      getAimReadiness(project.id, {
        pipeline: selectedWorkflow!.name,
        ...readinessInputs,
      }),
    enabled: Boolean(selectedWorkflow?.valid) && requiredInputsPresent,
    staleTime: 2_000,
    refetchInterval: requiredInputsPresent ? 5_000 : false,
  })
  const readinessInitialLoading =
    readinessQuery.isFetching && readinessQuery.data === undefined

  // Node chain + graph detail for the selected pipeline's info card.
  const detailQ = useQuery({
    queryKey: ['workflow-detail', selectedWorkflow?.name ?? '', targetWorkspace ?? ''],
    queryFn: () => getWorkflow(selectedWorkflow!.name, targetWorkspace),
    enabled: Boolean(selectedWorkflow),
    staleTime: 60_000,
  })

  const sessionsQuery = useQuery({
    queryKey: [...queryKeys.team.sessions.project(project.id), 'aim-runs'],
    queryFn: () => listTeamSessions(undefined, 30, { mode: 'aim', project_id: project.id }),
    refetchInterval: 5_000,
  })
  const runs = useMemo(() => sessionsQuery.data?.data ?? [], [sessionsQuery.data])

  // Join sessions with their workflow executions — one call for the table.
  const runIdsKey = useMemo(() => runs.map((r) => r.id).join(','), [runs])
  const executionsQuery = useQuery({
    queryKey: ['aim-run-executions', project.id, runIdsKey],
    queryFn: () => listWorkflowExecutions(runIdsKey.split(',').filter(Boolean)),
    enabled: runIdsKey.length > 0,
    refetchInterval: 5_000,
    // A new run changes the key — keep showing the old join instead of
    // flashing every row to the no-execution fallback for one render.
    placeholderData: keepPreviousData,
  })
  const executionBySession = useMemo(() => {
    // Newest-first from the API — keep the latest execution per session.
    const map = new Map<string, WorkflowExecutionSummary>()
    for (const ex of executionsQuery.data?.executions ?? []) {
      if (!map.has(ex.session_id)) map.set(ex.session_id, ex)
    }
    return map
  }, [executionsQuery.data])
  const runSummary = useMemo(() => {
    let active = 0
    let attention = 0
    for (const run of runs) {
      const status = displayStatus(Boolean(run.running), executionBySession.get(run.id))
      if (status === 'running' || status === 'waiting_gate') active += 1
      if (status === 'failed' || status === 'interrupted') attention += 1
    }
    return { total: runs.length, active, attention }
  }, [executionBySession, runs])

  // Runs & Reports folded in here: not every pipeline run produces an
  // aim_runs verdict (only compare/convert/test-kind calls do — assess,
  // understand, and a convert-unit's plan step never do), so this is a
  // side lookup keyed by session_id, not the table's row source. 100 is
  // generous relative to the sessions list's own limit below — a verdict
  // older than that won't show inline, but is still reachable by its own
  // deep link (getAimRun doesn't depend on this list).
  const aimRunsQuery = useQuery({
    queryKey: [...queryKeys.projects.detail(project.id), 'aim-runs-list'],
    queryFn: () => listAimRuns(project.id, 100),
    refetchInterval: 10_000,
  })
  const runBySessionId = useMemo(() => {
    const map = new Map<string, AimRunListItem>()
    for (const run of aimRunsQuery.data ?? []) {
      if (run.session_id) map.set(run.session_id, run)
    }
    return map
  }, [aimRunsQuery.data])

  const canRun =
    !starting &&
    Boolean(selectedWorkflow?.valid) &&
    requiredInputsPresent &&
    !readinessInitialLoading &&
    readinessQuery.data?.allowed === true

  // Builds the run's `inputs` payload from whatever the selected workflow
  // itself declares — works identically for the 6 known pipelines and any
  // rulebook-authored custom one, since neither is special-cased here.
  const buildInputs = useCallback((): Record<string, unknown> => {
    const result: Record<string, unknown> = {}
    for (const spec of selectedWorkflow?.inputs ?? []) {
      const raw = inputValues[spec.name]
      const value = raw === undefined || raw === '' ? spec.default : raw
      if (value === undefined) continue
      if (spec.type === 'number') result[spec.name] = Number(value)
      else if (spec.type === 'boolean') result[spec.name] = Boolean(value)
      else result[spec.name] = typeof value === 'string' ? value.trim() : value
    }
    return result
  }, [selectedWorkflow, inputValues])

  // Spec §3.3 — per-run sessions are named `<unit|wave>/<pipeline>` so the
  // run table and Discussion header read like the wireframe, not like UUIDs.
  const runLabel = useCallback((): string => {
    const shortName = selectedWorkflow
      ? pipelineDisplayName(selectedWorkflow.name)
      : (pipelineName ?? 'pipeline')
    const unitVal = inputValues.unit
    const waveVal = inputValues.wave
    if (typeof unitVal === 'string' && unitVal.trim()) return `${unitVal.trim()} · ${shortName}`
    if (waveVal !== undefined && waveVal !== '') return `wave ${waveVal} · ${shortName}`
    return shortName
  }, [selectedWorkflow, pipelineName, inputValues])

  const doRun = useCallback(async () => {
    if (!selectedWorkflow) return
    setStarting(true)
    setError(null)
    try {
      const readiness = await getAimReadiness(project.id, {
        pipeline: selectedWorkflow.name,
        ...readinessInputs,
      })
      if (!readiness.allowed) {
        throw new Error(readiness.blockers.join(' · ') || 'Pipeline prerequisites are not met.')
      }
      // Unapproved definitions get a one-click approve — the manifest is
      // the builtin pipeline's declared agents/tools (plan §7).
      if (!selectedWorkflow.approved) {
        await approveWorkflow(
          selectedWorkflow.name,
          selectedWorkflow.hash,
          targetWorkspace,
        )
        void queryClient.invalidateQueries({ queryKey: ['workflows'] })
      }
      // A fresh per-run session — parallel unit runs, self-contained
      // transcripts (spec §3.3).
      const session = await resolveTeamSession({
        mode: 'aim',
        project_id: project.id,
        create: true,
      })
      const title = runLabel()
      // Best-effort — a run with a UUID title still works, just reads worse.
      void updateTeamSessionTitle(session.id, title).catch(() => {})
      await runWorkflow(
        selectedWorkflow.name,
        session.id,
        buildInputs(),
        targetWorkspace,
      )
      void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessions.project(project.id) })
      void queryClient.invalidateQueries({ queryKey: ['aim-run-executions', project.id] })
      // Open the monitor right away — the whole point is watching it run.
      setDiscussion(null)
      setReportRun(null)
      setMonitorSession({ ...session, title, running: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start the pipeline run.')
    } finally {
      setStarting(false)
    }
  }, [
    selectedWorkflow,
    targetWorkspace,
    project.id,
    readinessInputs,
    buildInputs,
    runLabel,
    queryClient,
  ])

  // §9.3: convert pipelines write to the target repo — require explicit confirm.
  const handleRun = useCallback(() => {
    if (selectedWorkflow && CONVERT_WORKFLOW_NAMES.has(selectedWorkflow.name)) {
      setConfirmOpen(true)
    } else {
      void doRun()
    }
  }, [selectedWorkflow, doRun])

  const retryExecution = useCallback(
    async (run: SessionResponse, execution: WorkflowExecutionSummary) => {
      setStarting(true)
      setError(null)
      try {
        await runWorkflow(
          execution.definition_name,
          run.id,
          execution.inputs,
          targetWorkspace,
          execution.id,
        )
        void queryClient.invalidateQueries({
          queryKey: queryKeys.team.sessions.project(project.id),
        })
        setDiscussion(null)
        setReportRun(null)
        setMonitorSession({ id: run.id, title: run.title, running: true })
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to retry the pipeline run.')
      } finally {
        setStarting(false)
      }
    },
    [project.id, queryClient, targetWorkspace],
  )

  return (
    <div className="relative flex h-full min-h-0">
      <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-(--color-border) px-4 py-3">
          <p className="text-sm font-medium text-(--color-text)">Pipelines</p>
          {selectedWorkflow && !selectedWorkflow.approved && (
            <span
              className="flex items-center gap-1 rounded bg-(--bg-key) px-1.5 py-0.5 text-[10px] text-(--color-text-subtle)"
              title="First run approves this pipeline's manifest (its agents and tools)."
            >
              <ShieldCheck size={10} />
              approves on first run
            </span>
          )}
        </div>

        {/* Trigger form */}
        <div className="flex flex-wrap items-end gap-2 border-b border-(--color-border) p-4">
          <label className="flex w-full min-w-0 flex-col gap-1 text-xs text-(--color-text-muted) sm:w-auto">
            Pipeline
            <Combobox
              size="sm"
              value={pipelineName}
              onValueChange={setPipelineName}
              items={aimWorkflows.map((wf) => ({
                value: wf.name,
                label: pipelineDisplayName(wf.name),
                description: wf.description,
                meta: `${wf.node_count} nodes · ${wf.root}`,
                keywords: `${wf.name} ${wf.scope}`,
              }))}
              placeholder={workflowsQ.isLoading ? 'Loading…' : 'Select a pipeline…'}
              emptyText="No pipelines found."
              ariaLabel="Pipeline"
              searchPlaceholder="Search pipelines…"
              className="w-full sm:w-[320px]"
            />
          </label>
          {(selectedWorkflow?.inputs ?? []).map((spec) => (
            <WorkflowInputField
              key={spec.name}
              spec={spec}
              value={inputValues[spec.name]}
              onChange={(value) => setInputValue(spec.name, value)}
              unitOptions={unitOptions}
              waveOptions={waveOptions}
            />
          ))}
          <Button size="sm" onClick={() => handleRun()} disabled={!canRun || starting}>
            {starting ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
            Run
          </Button>
          {error && <p className="basis-full text-[11px] text-(--color-error)">{error}</p>}
        </div>

        {/* What this pipeline does — description, node chain, readiness. */}
        <PipelineInfoCard
          workflow={selectedWorkflow}
          graph={detailQ.data?.graph}
          readiness={readinessQuery.data}
          readinessLoading={readinessInitialLoading}
        />

        {/* Run table */}
        <div className="min-h-0 flex-1 overflow-auto p-4">
          {sessionsQuery.isLoading ? (
            <p className="text-xs text-(--color-text-subtle)">Loading runs…</p>
          ) : runs.length === 0 ? (
            <p className="text-xs text-(--color-text-subtle)">
              No runs yet — pick a pipeline and hit Run.
            </p>
          ) : (
            <section className="overflow-hidden rounded-md border border-(--color-border) bg-(--bg-page)">
              <div
                className={cn(
                  'flex min-h-11 flex-wrap items-center justify-between gap-2 bg-(--bg-subtle)/45 px-3 py-2',
                  !runHistoryCollapsed && 'border-b border-(--color-border)',
                )}
              >
                <div>
                  <p className="text-xs font-medium text-(--color-text)">Run history</p>
                  <p className="font-mono text-[9px] text-(--color-text-subtle)">
                    latest {runSummary.total} attempts
                  </p>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="flex items-center gap-1.5 text-[9px]">
                    {runSummary.active > 0 && (
                      <span className="inline-flex items-center gap-1 rounded border border-(--color-accent)/25 bg-(--color-accent)/5 px-1.5 py-0.5 text-(--color-accent)">
                        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
                        {runSummary.active} active
                      </span>
                    )}
                    {runSummary.attention > 0 && (
                      <span className="inline-flex items-center gap-1 rounded border border-(--color-error)/25 bg-(--color-error)/5 px-1.5 py-0.5 text-(--color-error)">
                        <CircleAlert size={9} />
                        {runSummary.attention} attention
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => setRunHistoryCollapsed((value) => !value)}
                    aria-expanded={!runHistoryCollapsed}
                    aria-controls="aim-run-history-table"
                    className="ml-1 inline-flex h-6 items-center gap-1 rounded px-1.5 text-[9px] font-medium text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
                    title={runHistoryCollapsed ? 'Expand run history' : 'Collapse run history'}
                  >
                    {runHistoryCollapsed ? (
                      <ChevronRight size={10} aria-hidden="true" />
                    ) : (
                      <ChevronDown size={10} aria-hidden="true" />
                    )}
                    {runHistoryCollapsed ? 'Expand' : 'Collapse'}
                  </button>
                </div>
              </div>
              {!runHistoryCollapsed && (
              <div id="aim-run-history-table" className="overflow-x-auto">
                <table className="w-full min-w-[760px] table-fixed text-left text-xs">
                  <colgroup>
                    <col className="w-[42%]" />
                    <col className="w-[18%]" />
                    <col className="w-[16%]" />
                    <col className="w-[10%]" />
                    <col className="w-[14%]" />
                  </colgroup>
                  <thead className="bg-(--bg-subtle)/25">
                    <tr className="h-8 text-[9px] uppercase text-(--color-text-subtle)">
                      <th className="px-3 font-medium">Run</th>
                      <th className="px-2 font-medium">State</th>
                      <th className="px-2 font-medium">Started</th>
                      <th className="px-2 font-medium">Duration</th>
                      <th className="px-2 text-right font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((run) => {
                      const aimRun = runBySessionId.get(run.id)
                      return (
                        <RunRow
                          key={run.id}
                          run={run}
                          execution={executionBySession.get(run.id)}
                          aimRun={aimRun}
                          monitorOpen={monitorSession?.id === run.id}
                          reportOpen={reportRun?.runId === aimRun?.id}
                          discussionOpen={discussion?.id === run.id}
                          onMonitor={() => {
                            setDiscussion(null)
                            setReportRun(null)
                            setMonitorSession((prev) =>
                              prev?.id === run.id ? null : run,
                            )
                          }}
                          onReport={() => {
                            if (!aimRun) return
                            setMonitorSession(null)
                            setDiscussion(null)
                            setReportRun((prev) =>
                              prev?.runId === aimRun.id
                                ? null
                                : {
                                    runId: aimRun.id,
                                    title: `${aimRun.unit} · ${aimRun.kind}`,
                                  },
                            )
                          }}
                          onDiscuss={() => {
                            setMonitorSession(null)
                            setReportRun(null)
                            setDiscussion((prev) =>
                              prev?.id === run.id ? null : run,
                            )
                          }}
                          onRetry={() => {
                            const execution = executionBySession.get(run.id)
                            if (execution) void retryExecution(run, execution)
                          }}
                        />
                      )
                    })}
                  </tbody>
                </table>
              </div>
              )}
            </section>
          )}
        </div>
      </div>

      {/* Run Monitor — node progress + per-node log + inline gate. Not chat. */}
      {monitorSession && !discussion && !reportRun && (() => {
        // Prefer the live row over the snapshot taken when the panel opened.
        const liveRun = runs.find((r) => r.id === monitorSession.id) ?? monitorSession
        return (
          <RunMonitorPanel
            sessionId={liveRun.id}
            title={liveRun.title}
            sessionRunning={Boolean(liveRun.running)}
            executionId={executionBySession.get(liveRun.id)?.id}
            onClose={() => setMonitorSession(null)}
            onDiscuss={() => {
              setMonitorSession(null)
              setReportRun(null)
              // liveRun may be the narrow monitor-only shape (opened from a
              // report deep link) — it never carries workspace either way,
              // so build the Discussion target explicitly rather than
              // reusing it as-is.
              setDiscussion({
                id: liveRun.id,
                title: liveRun.title,
                // liveRun's narrow-fallback branch has no workspace field at
                // all (undefined at runtime) — the cast just names that.
                workspace: (liveRun as SessionResponse).workspace ?? null,
              })
            }}
          />
        )
      })()}

      {/* Report — the aim_runs verdict/stats/JSON for a run that has one
          (Runs & Reports folded in here). Same singleton constraint. */}
      {reportRun && !discussion && !monitorSession && (
        <ReportPanel
          projectId={project.id}
          runId={reportRun.runId}
          title={reportRun.title}
          onClose={() => setReportRun(null)}
          onOpenNodes={(sessionId) => {
            setReportRun(null)
            setDiscussion(null)
            // No known executionId here — RunMonitorPanel resolves one
            // from sessionId alone (same fallback a just-started run uses).
            setMonitorSession({ id: sessionId, title: reportRun.title ?? null, running: false })
          }}
        />
      )}

      {/* Post-run Discussion — TeamChatView is a global singleton; exactly one
          instance, mounted only while a finished run's transcript is open. */}
      {discussion && !monitorSession && !reportRun && (
        <AimSidePanel storageKey={STORAGE_KEYS.panels.aimDiscussion} defaultWidth={420}>
          <header className="flex shrink-0 items-center justify-between gap-3 border-b border-(--color-border) px-4 py-3">
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-(--color-text)">Discussion</h2>
              <p className="mt-0.5 truncate text-xs text-(--color-text-subtle)">
                {discussion.title ?? discussion.id.slice(0, 8)}
              </p>
            </div>
            <button
              type="button"
              onClick={() => setDiscussion(null)}
              aria-label="Close discussion"
              title="Close"
              className="rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            >
              <X size={16} />
            </button>
          </header>
          <div className="min-h-0 flex-1 overflow-hidden">
            <TeamChatView
              sessionId={discussion.id}
              mode="aim"
              workspace={discussion.workspace ?? null}
            />
          </div>
        </AimSidePanel>
      )}

      {/* §9.3 — Confirm dialog for convert pipelines (write to target repo) */}
      {confirmOpen && (
        <div
          className="absolute inset-0 z-(--z-modal) flex items-center justify-center bg-black/40"
          role="dialog"
          aria-modal="true"
        >
          <div className="w-80 rounded-xl border border-(--color-border) bg-(--bg-card) p-5 shadow-xl">
            <div className="mb-3 flex items-start gap-2">
              <AlertTriangle size={16} className="mt-0.5 shrink-0 text-(--color-warning,orange)" />
              <div>
                <p className="text-sm font-medium text-(--color-text)">
                  Write to target repo?
                </p>
                <p className="mt-1 text-xs text-(--color-text-muted)">
                  <strong>
                    {selectedWorkflow ? pipelineDisplayName(selectedWorkflow.name) : 'This pipeline'}
                  </strong>{' '}
                  will write converted output to the target source directory. This cannot be
                  undone automatically.
                </p>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => setConfirmOpen(false)}>
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={() => { setConfirmOpen(false); void doRun() }}
              >
                Run anyway
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Pipeline info card ────────────────────────────────────────────────────────

function NodeKindIcon({ kind }: { kind: string }) {
  switch (kind) {
    case 'agent':
      return <Bot size={14} className="shrink-0 text-(--accent-purple)" />
    case 'gate':
    case 'input':
      return <CirclePause size={14} className="shrink-0 text-(--color-warning,orange)" />
    case 'tool':
      return <Wrench size={14} className="shrink-0 text-(--color-info)" />
    case 'foreach':
      return <Repeat size={14} className="shrink-0 text-(--color-success)" />
    case 'notify':
      return <Bell size={14} className="shrink-0 text-(--color-text-muted)" />
    default:
      return <Shuffle size={14} className="shrink-0 text-(--color-accent)" />
  }
}

interface WorkflowCanvasNode {
  id: string
  kind: string
  tool?: string
  title?: string
  prompt?: string
  body?: string
  message?: string
  question?: string
  items?: string
  value?: string
  choices?: string[]
  subagents?: string[]
  args?: Record<string, unknown>
}

interface WorkflowCanvasEdge {
  from: string
  to: string
  when?: string
}

interface PositionedWorkflowNode extends WorkflowCanvasNode {
  x: number
  y: number
}

const WORKFLOW_NODE_WIDTH = 186
const WORKFLOW_NODE_HEIGHT = 66
const WORKFLOW_COLUMN_GAP = 78
const WORKFLOW_ROW_GAP = 30
const WORKFLOW_CANVAS_PADDING = 28
const WORKFLOW_VIEWPORT_HEIGHT = 272
const WORKFLOW_MIN_ZOOM = 0.65

function layoutWorkflowGraph(nodes: WorkflowCanvasNode[], edges: WorkflowCanvasEdge[]) {
  const nodeIds = new Set(nodes.map((node) => node.id))
  const outgoing = new Map<string, string[]>()
  const indegree = new Map(nodes.map((node) => [node.id, 0]))
  const level = new Map(nodes.map((node) => [node.id, 0]))

  for (const edge of edges) {
    if (!nodeIds.has(edge.from) || !nodeIds.has(edge.to)) continue
    outgoing.set(edge.from, [...(outgoing.get(edge.from) ?? []), edge.to])
    indegree.set(edge.to, (indegree.get(edge.to) ?? 0) + 1)
  }

  const queue = nodes.filter((node) => indegree.get(node.id) === 0).map((node) => node.id)
  const visited = new Set<string>()
  while (queue.length > 0) {
    const id = queue.shift() as string
    if (visited.has(id)) continue
    visited.add(id)
    for (const target of outgoing.get(id) ?? []) {
      level.set(target, Math.max(level.get(target) ?? 0, (level.get(id) ?? 0) + 1))
      indegree.set(target, (indegree.get(target) ?? 1) - 1)
      if (indegree.get(target) === 0) queue.push(target)
    }
  }

  // Invalid cyclic definitions are surfaced elsewhere; keep their preview usable.
  let fallbackLevel = Math.max(0, ...level.values())
  for (const node of nodes) {
    if (!visited.has(node.id)) {
      fallbackLevel += 1
      level.set(node.id, fallbackLevel)
    }
  }

  const columns = new Map<number, WorkflowCanvasNode[]>()
  for (const node of nodes) {
    const column = level.get(node.id) ?? 0
    columns.set(column, [...(columns.get(column) ?? []), node])
  }
  const maxRows = Math.max(1, ...[...columns.values()].map((column) => column.length))
  const rowStride = WORKFLOW_NODE_HEIGHT + WORKFLOW_ROW_GAP
  const positioned: PositionedWorkflowNode[] = []
  for (const [columnIndex, columnNodes] of columns) {
    const columnOffset = ((maxRows - columnNodes.length) * rowStride) / 2
    columnNodes.forEach((node, rowIndex) => {
      positioned.push({
        ...node,
        x: WORKFLOW_CANVAS_PADDING + columnIndex * (WORKFLOW_NODE_WIDTH + WORKFLOW_COLUMN_GAP),
        y: WORKFLOW_CANVAS_PADDING + columnOffset + rowIndex * rowStride,
      })
    })
  }

  const maxLevel = Math.max(0, ...level.values())
  return {
    nodes: positioned,
    width:
      WORKFLOW_CANVAS_PADDING * 2 +
      WORKFLOW_NODE_WIDTH +
      maxLevel * (WORKFLOW_NODE_WIDTH + WORKFLOW_COLUMN_GAP),
    height: Math.max(
      210,
      WORKFLOW_CANVAS_PADDING * 2 + maxRows * WORKFLOW_NODE_HEIGHT + (maxRows - 1) * WORKFLOW_ROW_GAP,
    ),
  }
}

function workflowNodeTone(kind: string): string {
  switch (kind) {
    case 'gate':
    case 'input':
      return 'border-(--color-warning,orange)/60 bg-(--color-warning-subtle)/25'
    case 'agent':
      return 'border-(--accent-purple)/55 bg-(--accent-purple-soft)/20'
    case 'tool':
      return 'border-(--color-info)/50 bg-(--color-info-subtle)/20'
    case 'foreach':
      return 'border-(--color-success)/50 bg-(--color-success-subtle)/20'
    default:
      return 'border-(--color-border)'
  }
}

function workflowNodeAccent(kind: string): string {
  switch (kind) {
    case 'gate':
    case 'input':
      return 'bg-(--color-warning,orange)'
    case 'agent':
      return 'bg-(--accent-purple)'
    case 'tool':
      return 'bg-(--color-info)'
    case 'foreach':
      return 'bg-(--color-success)'
    default:
      return 'bg-(--color-text-muted)'
  }
}

function workflowNodeIconTone(kind: string): string {
  switch (kind) {
    case 'gate':
    case 'input':
      return 'border-(--color-warning,orange)/30 bg-(--color-warning-subtle)/35'
    case 'agent':
      return 'border-(--accent-purple)/30 bg-(--accent-purple-soft)/35'
    case 'tool':
      return 'border-(--color-info)/30 bg-(--color-info-subtle)/35'
    case 'foreach':
      return 'border-(--color-success)/30 bg-(--color-success-subtle)/35'
    default:
      return 'border-(--color-border) bg-(--bg-key)'
  }
}

function workflowNodeSummary(node: WorkflowCanvasNode): string {
  switch (node.kind) {
    case 'agent':
      return node.subagents?.length ? node.subagents.join(', ') : 'Lead agent'
    case 'gate':
      return node.title ?? `${node.choices?.length ?? 0} decision options`
    case 'input':
      return node.question ?? 'User input'
    case 'tool':
      return node.tool ?? 'Deterministic action'
    case 'foreach':
      return node.items ? `Each item · ${node.items}` : 'Sequential batch'
    case 'notify':
      return node.title ?? node.message ?? 'Notification'
    case 'switch':
      return node.value ? `Route · ${node.value}` : 'Conditional route'
    default:
      return 'Workflow step'
  }
}

function workflowNodeInstruction(node: WorkflowCanvasNode): string | null {
  return node.prompt ?? node.body ?? node.message ?? node.question ?? null
}

function orthogonalWorkflowEdge(
  startX: number,
  startY: number,
  endX: number,
  endY: number,
  outerLaneY?: number,
) {
  const roundedPath = (points: Array<{ x: number; y: number }>) => {
    if (points.length < 2) return ''
    const commands = [`M ${points[0].x} ${points[0].y}`]
    for (let index = 1; index < points.length; index += 1) {
      const current = points[index]
      const next = points[index + 1]
      if (!next) {
        commands.push(`L ${current.x} ${current.y}`)
        continue
      }
      const previous = points[index - 1]
      const incomingLength = Math.hypot(current.x - previous.x, current.y - previous.y)
      const outgoingLength = Math.hypot(next.x - current.x, next.y - current.y)
      const radius = Math.min(9, incomingLength / 2, outgoingLength / 2)
      const before = {
        x: current.x - ((current.x - previous.x) / incomingLength) * radius,
        y: current.y - ((current.y - previous.y) / incomingLength) * radius,
      }
      const after = {
        x: current.x + ((next.x - current.x) / outgoingLength) * radius,
        y: current.y + ((next.y - current.y) / outgoingLength) * radius,
      }
      commands.push(
        `L ${before.x} ${before.y}`,
        `Q ${current.x} ${current.y} ${after.x} ${after.y}`,
      )
    }
    return commands.join(' ')
  }

  if (Math.abs(endY - startY) < 1) {
    return {
      path: `M ${startX} ${startY} H ${endX}`,
      labelX: (startX + endX) / 2,
      labelY: startY - 7,
    }
  }
  if (outerLaneY !== undefined) {
    const exitX = startX + 28
    const entryX = endX - 28
    return {
      path: roundedPath([
        { x: startX, y: startY },
        { x: exitX, y: startY },
        { x: exitX, y: outerLaneY },
        { x: entryX, y: outerLaneY },
        { x: entryX, y: endY },
        { x: endX, y: endY },
      ]),
      labelX: (exitX + entryX) / 2,
      labelY: outerLaneY - 7,
    }
  }
  const foldX = startX + (endX - startX) * 0.5
  return {
    path: roundedPath([
      { x: startX, y: startY },
      { x: foldX, y: startY },
      { x: foldX, y: endY },
      { x: endX, y: endY },
    ]),
    labelX: (foldX + endX) / 2,
    labelY: endY - 8,
  }
}

function WorkflowCanvasPreview({
  nodes,
  edges,
}: {
  nodes: WorkflowCanvasNode[]
  edges: WorkflowCanvasEdge[]
}) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const [zoom, setZoom] = useState(0.82)
  const [collapsed, setCollapsed] = useState(false)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const layout = useMemo(() => layoutWorkflowGraph(nodes, edges), [edges, nodes])
  const nodeById = useMemo(
    () => new Map(layout.nodes.map((node) => [node.id, node])),
    [layout.nodes],
  )
  const selectedNode = selectedNodeId
    ? (nodes.find((node) => node.id === selectedNodeId) ?? null)
    : null
  const incomingEdges = selectedNode
    ? edges.filter((edge) => edge.to === selectedNode.id)
    : []
  const outgoingEdges = selectedNode
    ? edges.filter((edge) => edge.from === selectedNode.id)
    : []

  const fit = () => {
    const viewportWidth = viewportRef.current?.clientWidth ?? layout.width
    setZoom(Math.max(WORKFLOW_MIN_ZOOM, Math.min(1, (viewportWidth - 28) / layout.width)))
    viewportRef.current?.scrollTo({ left: 0, top: 0, behavior: 'smooth' })
  }

  return (
    <div className="overflow-hidden rounded-md border border-(--color-border) bg-(--bg-page)">
      <div
        className={cn(
          'flex h-8 items-center justify-between bg-(--bg-subtle)/70 px-2.5',
          !collapsed && 'border-b border-(--color-border)',
        )}
      >
        <span className="font-mono text-[9px] text-(--color-text-subtle)">
          graph · {nodes.length} nodes · {edges.length} routes
        </span>
        <div className="flex items-center gap-0.5">
          {!collapsed && (
            <>
          <button
            type="button"
            onClick={() => setZoom((value) => Math.max(WORKFLOW_MIN_ZOOM, value - 0.1))}
            className="flex h-5 w-5 items-center justify-center rounded text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Zoom workflow graph out"
            title="Zoom out"
          >
            <Minus size={10} />
          </button>
          <span className="w-9 text-center font-mono text-[9px] text-(--color-text-subtle)">
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            onClick={() => setZoom((value) => Math.min(1.2, value + 0.1))}
            className="flex h-5 w-5 items-center justify-center rounded text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Zoom workflow graph in"
            title="Zoom in"
          >
            <Plus size={10} />
          </button>
          <button
            type="button"
            onClick={fit}
            className="ml-1 flex h-5 w-5 items-center justify-center rounded text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Fit workflow graph"
            title="Fit graph"
          >
            <Maximize2 size={10} />
          </button>
            </>
          )}
          <button
            type="button"
            onClick={() => setCollapsed((value) => !value)}
            aria-expanded={!collapsed}
            aria-controls="workflow-canvas-content"
            className="ml-1 inline-flex h-5 items-center gap-1 rounded px-1.5 text-[9px] font-medium text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
            title={collapsed ? 'Expand canvas preview' : 'Collapse canvas preview'}
          >
            {collapsed ? (
              <ChevronRight size={10} aria-hidden="true" />
            ) : (
              <ChevronDown size={10} aria-hidden="true" />
            )}
            {collapsed ? 'Expand' : 'Collapse'}
          </button>
        </div>
      </div>

      {!collapsed && (
      <div id="workflow-canvas-content">
      <div
        ref={viewportRef}
        className="h-[272px] overflow-auto"
        style={{
          backgroundImage:
            'radial-gradient(color-mix(in srgb, var(--color-border) 80%, transparent) 1px, transparent 1px)',
          backgroundSize: '16px 16px',
        }}
      >
        <div
          className="relative"
          style={{
            width: layout.width * zoom,
            height: Math.max(WORKFLOW_VIEWPORT_HEIGHT, layout.height * zoom),
          }}
        >
          <div
            className="absolute left-0 top-0 origin-top-left"
            style={{
              width: layout.width,
              height: layout.height,
              top: Math.max(0, (WORKFLOW_VIEWPORT_HEIGHT - layout.height * zoom) / 2),
              transform: `scale(${zoom})`,
            }}
          >
            <svg
              className="pointer-events-none absolute inset-0 h-full w-full"
              viewBox={`0 0 ${layout.width} ${layout.height}`}
              aria-hidden="true"
            >
              <defs>
                <marker
                  id="workflow-edge-arrow"
                  markerWidth="8"
                  markerHeight="8"
                  refX="7"
                  refY="4"
                  orient="auto"
                >
                  <path d="M0,0 L8,4 L0,8 Z" fill="var(--color-text-muted)" />
                </marker>
                <marker
                  id="workflow-edge-arrow-branch"
                  markerWidth="8"
                  markerHeight="8"
                  refX="7"
                  refY="4"
                  orient="auto"
                >
                  <path d="M0,0 L8,4 L0,8 Z" fill="var(--color-warning)" />
                </marker>
              </defs>
              {edges.map((edge, index) => {
                const source = nodeById.get(edge.from)
                const target = nodeById.get(edge.to)
                if (!source || !target) return null
                const startX = source.x + WORKFLOW_NODE_WIDTH
                const startY = source.y + WORKFLOW_NODE_HEIGHT / 2
                const endX = target.x
                const endY = target.y + WORKFLOW_NODE_HEIGHT / 2
                const skipsColumns =
                  endX - startX >
                  (WORKFLOW_NODE_WIDTH + WORKFLOW_COLUMN_GAP) * 1.45
                const outerLaneY = skipsColumns
                  ? endY >= startY
                    ? layout.height - 10
                    : 10
                  : undefined
                const routed = orthogonalWorkflowEdge(
                  startX,
                  startY,
                  endX,
                  endY,
                  outerLaneY,
                )
                const conditional = Boolean(edge.when && edge.when !== '*')
                const connected = Boolean(
                  selectedNode &&
                    (edge.from === selectedNode.id || edge.to === selectedNode.id),
                )
                return (
                  <g
                    key={`${edge.from}-${edge.to}-${edge.when ?? index}`}
                    opacity={selectedNode ? (connected ? 1 : 0.28) : 1}
                  >
                    <path
                      d={routed.path}
                      fill="none"
                      stroke={conditional ? 'var(--color-warning)' : 'var(--color-text-muted)'}
                      strokeOpacity={conditional ? 0.82 : 0.68}
                      strokeWidth={connected ? 2 : 1.35}
                      strokeLinejoin="round"
                      markerEnd={
                        conditional
                          ? 'url(#workflow-edge-arrow-branch)'
                          : 'url(#workflow-edge-arrow)'
                      }
                    />
                    {conditional && (
                      <text
                        x={routed.labelX}
                        y={routed.labelY}
                        textAnchor="middle"
                        fill="var(--color-warning)"
                        stroke="var(--bg-page)"
                        strokeWidth="4"
                        paintOrder="stroke"
                        fontSize="9"
                        fontWeight="600"
                        fontFamily="var(--font-mono)"
                      >
                        {edge.when}
                      </text>
                    )}
                  </g>
                )
              })}
            </svg>

            {layout.nodes.map((node) => (
              <button
                type="button"
                key={node.id}
                onClick={() =>
                  setSelectedNodeId((current) => (current === node.id ? null : node.id))
                }
                aria-pressed={selectedNode?.id === node.id}
                className={cn(
                  'absolute rounded-lg border bg-(--bg-card) text-left shadow-sm outline-none transition-[border-color,box-shadow,opacity] hover:border-(--color-border-strong) focus-visible:ring-2 focus-visible:ring-(--focus-ring)/40',
                  workflowNodeTone(node.kind),
                  selectedNode?.id === node.id
                    ? 'ring-2 ring-(--color-accent)/35 shadow-md'
                    : selectedNode && 'opacity-80 hover:opacity-100',
                )}
                style={{
                  left: node.x,
                  top: node.y,
                  width: WORKFLOW_NODE_WIDTH,
                  height: WORKFLOW_NODE_HEIGHT,
                }}
                title={`Inspect ${node.id}`}
              >
                <span className="absolute -left-[5px] top-[28px] h-2.5 w-2.5 rounded-full border-2 border-(--bg-page) bg-(--color-text-muted) shadow-sm" />
                <span className={cn('absolute -right-[5px] top-[28px] h-2.5 w-2.5 rounded-full border-2 border-(--bg-page) shadow-sm', workflowNodeAccent(node.kind))} />
                <span className="flex h-full min-w-0 items-center gap-2.5 px-3">
                  <span
                    className={cn(
                      'flex h-8 w-8 shrink-0 items-center justify-center rounded-md border',
                      workflowNodeIconTone(node.kind),
                    )}
                  >
                    <NodeKindIcon kind={node.kind} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[8px] font-semibold uppercase text-(--color-text-subtle)">
                      {node.kind}
                    </span>
                    <span className="mt-0.5 line-clamp-2 block font-mono text-[11px] font-semibold leading-3.5 text-(--color-text)">
                      {node.id}
                    </span>
                    <span className="mt-0.5 block truncate text-[8px] text-(--color-text-subtle)">
                      {workflowNodeSummary(node)}
                    </span>
                  </span>
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {selectedNode && (
        <div className="border-t border-(--color-border) bg-(--bg-subtle)/45 p-3">
          <div className="flex min-w-0 items-start gap-2.5">
            <span
              className={cn(
                'flex h-8 w-8 shrink-0 items-center justify-center rounded-md border',
                workflowNodeIconTone(selectedNode.kind),
              )}
            >
              <NodeKindIcon kind={selectedNode.kind} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-mono text-xs font-semibold text-(--color-text)">
                  {selectedNode.id}
                </span>
                <span className="rounded bg-(--bg-key) px-1.5 py-0.5 text-[8px] font-semibold uppercase text-(--color-text-subtle)">
                  {selectedNode.kind}
                </span>
                {selectedNode.tool && (
                  <span className="rounded bg-(--color-info-subtle)/35 px-1.5 py-0.5 font-mono text-[9px] text-(--color-info)">
                    {selectedNode.tool}
                  </span>
                )}
              </div>
              <p className="mt-1 text-[10px] leading-4 text-(--color-text-muted)">
                {workflowNodeSummary(selectedNode)}
              </p>
            </div>
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[9px] text-(--color-text-subtle)">
            <span className="font-semibold uppercase">Routes</span>
            {incomingEdges.length === 0 && (
              <span className="rounded border border-(--color-border) px-1.5 py-0.5">entry</span>
            )}
            {incomingEdges.map((edge) => (
              <span
                key={`in-${edge.from}-${edge.when ?? ''}`}
                className="rounded border border-(--color-border) px-1.5 py-0.5 font-mono"
              >
                {edge.from} →
              </span>
            ))}
            {outgoingEdges.map((edge) => (
              <span
                key={`out-${edge.to}-${edge.when ?? ''}`}
                className={cn(
                  'rounded border px-1.5 py-0.5 font-mono',
                  edge.when && edge.when !== '*'
                    ? 'border-(--color-warning,orange)/40 text-(--color-warning,orange)'
                    : 'border-(--color-border)',
                )}
              >
                → {edge.to}{edge.when && edge.when !== '*' ? ` · ${edge.when}` : ''}
              </span>
            ))}
            {outgoingEdges.length === 0 && (
              <span className="rounded border border-(--color-border) px-1.5 py-0.5">terminal</span>
            )}
          </div>

          {(selectedNode.choices?.length || selectedNode.subagents?.length) && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {selectedNode.subagents?.map((agent) => (
                <span key={agent} className="rounded bg-(--accent-purple-soft)/35 px-1.5 py-0.5 text-[9px] text-(--accent-purple)">
                  agent · {agent}
                </span>
              ))}
              {selectedNode.choices?.map((choice) => (
                <span key={choice} className="rounded bg-(--color-warning-subtle)/35 px-1.5 py-0.5 text-[9px] text-(--color-warning,orange)">
                  choice · {choice}
                </span>
              ))}
            </div>
          )}

          {workflowNodeInstruction(selectedNode) && (
            <details className="mt-2 rounded border border-(--color-border) bg-(--bg-page)">
              <summary className="cursor-pointer px-2 py-1.5 text-[9px] font-medium text-(--color-text-muted)">
                View full instruction
              </summary>
              <pre className="max-h-36 overflow-auto whitespace-pre-wrap border-t border-(--color-border) p-2 font-mono text-[9px] leading-4 text-(--color-text-2)">
                {workflowNodeInstruction(selectedNode)}
              </pre>
            </details>
          )}

          {selectedNode.args && Object.keys(selectedNode.args).length > 0 && (
            <details className="mt-2 rounded border border-(--color-border) bg-(--bg-page)">
              <summary className="cursor-pointer px-2 py-1.5 text-[9px] font-medium text-(--color-text-muted)">
                View tool arguments
              </summary>
              <pre className="max-h-36 overflow-auto whitespace-pre-wrap border-t border-(--color-border) p-2 font-mono text-[9px] leading-4 text-(--color-text-2)">
                {JSON.stringify(selectedNode.args, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}
      </div>
      )}
    </div>
  )
}

function PipelineInfoCard({
  workflow,
  graph,
  readiness,
  readinessLoading,
}: {
  workflow: WorkflowListItem | undefined
  graph: Record<string, unknown> | undefined
  readiness: AimReadiness | undefined
  readinessLoading: boolean
}) {
  if (!workflow) return null
  const workflowInputs = workflow.inputs ?? []
  const workflowErrors = workflow.errors ?? []
  const readinessWarnings = readiness?.warnings ?? []
  const nodes = Array.isArray(graph?.nodes)
    ? (graph.nodes as Array<Record<string, unknown>>)
        .filter((node) => typeof node?.id === 'string' && typeof node?.kind === 'string')
        .map((node): WorkflowCanvasNode => ({
          id: node.id as string,
          kind: node.kind as string,
          tool: typeof node.tool === 'string' ? node.tool : undefined,
          title: typeof node.title === 'string' ? node.title : undefined,
          prompt: typeof node.prompt === 'string' ? node.prompt : undefined,
          body: typeof node.body === 'string' ? node.body : undefined,
          message: typeof node.message === 'string' ? node.message : undefined,
          question: typeof node.question === 'string' ? node.question : undefined,
          items: typeof node.items === 'string' ? node.items : undefined,
          value: typeof node.value === 'string' ? node.value : undefined,
          choices: Array.isArray(node.choices)
            ? node.choices.filter((choice): choice is string => typeof choice === 'string')
            : undefined,
          subagents: Array.isArray(node.subagents)
            ? node.subagents.filter((agent): agent is string => typeof agent === 'string')
            : undefined,
          args:
            typeof node.args === 'object' && node.args !== null
              ? (node.args as Record<string, unknown>)
              : undefined,
        }))
    : []
  const nodeIds = new Set(nodes.map((node) => node.id))
  const edges = Array.isArray(graph?.edges)
    ? (graph.edges as Array<{ from?: string; to?: string; when?: string }>)
        .filter(
          (edge) =>
            typeof edge?.from === 'string' &&
            typeof edge?.to === 'string' &&
            nodeIds.has(edge.from) &&
            nodeIds.has(edge.to),
        )
        .map((edge) => ({
          from: edge.from as string,
          to: edge.to as string,
          when: typeof edge.when === 'string' ? edge.when : undefined,
        }))
    : []
  const gateCount = nodes.filter((n) => n.kind === 'gate' || n.kind === 'input').length
  const claimDependencies = readiness?.claim_dependencies ?? []
  const claimBlockerPrefix = 'selected unit(s) are owned by'
  const visibleBlockers = claimDependencies.length
    ? (readiness?.blockers ?? []).filter(
        (blocker) => !blocker.includes(claimBlockerPrefix),
      )
    : (readiness?.blockers ?? [])

  return (
    <div className="space-y-2 border-b border-(--color-border) px-4 py-3">
      <p className="text-xs leading-5 text-(--color-text-muted)">
        {workflow.description}
        {gateCount > 0 && (
          <span className="ml-1.5 text-(--color-warning,orange)">
            · {gateCount} human gate{gateCount > 1 ? 's' : ''}
          </span>
        )}
      </p>

      {/* Theme-aware DAG preview from the workflow's real nodes and edges. */}
      {nodes.length > 0 && (
        <WorkflowCanvasPreview nodes={nodes} edges={edges} />
      )}

      {/* Inputs + readiness */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {workflowInputs.length > 0 && (
          <span className="flex items-center gap-1.5 text-[11px] text-(--color-text-subtle)">
            inputs:
            {workflowInputs.map((input) => (
              <span key={input.name} className="rounded bg-(--bg-key) px-1.5 py-0.5 font-mono text-[10px] text-(--color-text-2)">
                {input.name}: {input.type}
                {input.required ? '' : '?'}
              </span>
            ))}
          </span>
        )}
        {!workflow.valid && (
          <span className="text-[11px] text-(--color-error)" title={workflowErrors.join('\n')}>
            definition invalid — {workflowErrors[0] ?? 'see errors'}
          </span>
        )}
      </div>
      {readinessLoading ? (
        <p className="text-[11px] text-(--color-text-subtle)">Checking prerequisites…</p>
      ) : readiness ? (
        <div
          className={cn(
            'rounded-md px-2.5 py-2 text-[11px]',
            readiness.allowed
              ? 'bg-(--color-success-bg,var(--bg-key)) text-(--color-success)'
              : 'bg-(--color-error-subtle,var(--bg-key)) text-(--color-error)',
          )}
        >
          <p className="font-medium">
            {readiness.allowed
              ? `Ready · ${readiness.selected_count} unit(s) selected`
              : `Blocked · ${visibleBlockers.length + claimDependencies.length} prerequisite(s)`}
          </p>
          {claimDependencies.length > 0 && (
            <div className="mt-2 space-y-1.5">
              {claimDependencies.map((dependency) => (
                <div
                  key={dependency.workflow_execution_id}
                  className="rounded-md border border-(--color-warning,orange)/35 bg-(--bg-page)/70 px-2.5 py-2 text-(--color-text-2)"
                >
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="inline-flex items-center gap-1 font-medium text-(--color-warning,orange)">
                      <CirclePause size={11} aria-hidden="true" />
                      Active workflow dependency
                    </span>
                    <span className="rounded bg-(--bg-key) px-1.5 py-0.5 font-mono text-[9px] uppercase text-(--color-text-muted)">
                      {dependency.execution_status}
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-[10px]">
                    {dependency.workflow_name}
                    <span className="ml-1.5 text-(--color-text-subtle)">
                      · {dependency.workflow_execution_id.slice(0, 8)}
                    </span>
                  </p>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {(dependency.units ?? []).map((unit) => (
                      <span
                        key={unit}
                        className="rounded border border-(--color-border) bg-(--bg-subtle) px-1.5 py-0.5 font-mono text-[9px] text-(--color-text-muted)"
                      >
                        {unit}
                      </span>
                    ))}
                  </div>
                  <p className="mt-1.5 text-[9px] text-(--color-text-subtle)">
                    Locked until{' '}
                    {new Date(dependency.lease_expires_at).toLocaleString([], {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </p>
                </div>
              ))}
            </div>
          )}
          {!readiness.allowed && visibleBlockers.length > 0 && (
            <ul className="mt-1 list-disc space-y-0.5 pl-4">
              {visibleBlockers.slice(0, 4).map((blocker) => (
                <li key={blocker}>{blocker}</li>
              ))}
            </ul>
          )}
          {readinessWarnings.map((warning) => (
            <p key={warning} className="mt-1 text-(--color-warning,orange)">
              {warning}
            </p>
          ))}
        </div>
      ) : null}
    </div>
  )
}

// ── Run Monitor ───────────────────────────────────────────────────────────────

/** Node progress + per-node debug log + inline gate for one run. Reused by
 * Runs & Reports for finished runs (pass `executionId` directly). */
export function RunMonitorPanel({
  sessionId,
  title,
  sessionRunning,
  executionId: knownExecutionId,
  onClose,
  onDiscuss,
}: {
  sessionId: string
  title?: string | null
  sessionRunning: boolean
  executionId?: string | null
  onClose: () => void
  onDiscuss?: () => void
}) {
  // The table's 5s join may not have caught a just-started run — resolve the
  // session's newest execution ourselves until one shows up. Give up after
  // ~30s: a session with no execution by then never ran a workflow (e.g. an
  // aim_runs row written outside the pipeline path).
  const lookupQ = useQuery({
    queryKey: ['aim-monitor-execution', sessionId],
    queryFn: () => listWorkflowExecutions([sessionId]),
    enabled: !knownExecutionId && sessionId.length > 0,
    refetchInterval: (query) =>
      query.state.data?.executions.length === 0 && query.state.dataUpdateCount >= 12
        ? false
        : 2_500,
  })
  // UseQueryResult doesn't expose the internal Query's dataUpdateCount, only
  // dataUpdatedAt (a timestamp) — count fetch completions ourselves off that.
  const lookupFetchCountRef = useRef(0)
  const lastLookupUpdateRef = useRef<number | null>(null)
  if (lookupQ.dataUpdatedAt && lookupQ.dataUpdatedAt !== lastLookupUpdateRef.current) {
    lastLookupUpdateRef.current = lookupQ.dataUpdatedAt
    lookupFetchCountRef.current += 1
  }
  const executionId = knownExecutionId ?? lookupQ.data?.executions[0]?.id
  const lookupExhausted =
    !knownExecutionId && !executionId && lookupFetchCountRef.current >= 12

  const detailQ = useQuery({
    queryKey: ['workflow-execution', executionId ?? ''],
    queryFn: () => getExecution(executionId as string),
    enabled: Boolean(executionId),
    refetchInterval: (query) => {
      const status = query.state.data?.execution.status
      return status === 'running' || status === 'waiting_gate' ? 2_500 : false
    },
  })
  const execution = detailQ.data?.execution
  const nodeRuns = detailQ.data?.node_runs ?? []
  const status = displayStatus(sessionRunning, execution)
  const active = status === 'running' || status === 'waiting_gate'
  const completedNodeCount = nodeRuns.filter((node) =>
    ['succeeded', 'failed', 'skipped'].includes(node.status),
  ).length
  const runningNode = [...nodeRuns].reverse().find((node) => node.status === 'running')
  const executionInputs = Object.entries(execution?.inputs ?? {}).filter(
    ([, value]) => value !== null && value !== undefined && value !== '',
  )

  const [stopping, setStopping] = useState(false)
  const stop = async () => {
    if (!executionId) return
    setStopping(true)
    try {
      await stopExecution(executionId)
      void detailQ.refetch()
    } catch {
      // Already finished (404) — the next poll shows the terminal state.
    } finally {
      setStopping(false)
    }
  }

  return (
    <AimSidePanel
      storageKey={STORAGE_KEYS.panels.aimMonitor}
      defaultWidth={500}
      minWidth={340}
      maxWidth={840}
    >
      <div className="sticky top-0 z-10 border-b border-(--color-border) bg-(--bg-page)/95 backdrop-blur-sm">
        <div className="flex h-11 items-center justify-between gap-3 px-4">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-(--color-border) bg-(--bg-key) text-(--color-text-muted)">
              <Activity size={13} aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase text-(--color-text-subtle)">
                Run monitor
              </p>
              <p
                className="truncate text-xs font-medium text-(--color-text)"
                title={title ?? undefined}
              >
                {title ?? sessionId.slice(0, 8)}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
          {active && executionId && (
            <button
              type="button"
              onClick={() => void stop()}
              disabled={stopping}
              className="flex h-7 items-center gap-1.5 rounded-md px-2 text-[11px] font-medium text-(--color-error) transition-colors hover:bg-(--color-error)/10 disabled:opacity-50"
              title="Stop this run"
            >
              {stopping ? <Loader2 size={11} className="animate-spin" /> : <OctagonX size={11} />}
              Stop
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close run monitor"
            className="flex h-7 w-7 items-center justify-center rounded-md text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
          >
            <X size={16} />
          </button>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* Execution summary */}
        <section className="border-b border-(--color-border) bg-(--bg-subtle)/35 px-4 py-3">
          {!execution ? (
            lookupExhausted ? (
              <div className="flex items-start gap-2 text-xs text-(--color-text-muted)">
                <CircleAlert size={14} className="mt-0.5 shrink-0" />
                <span>No workflow execution is recorded for this run.</span>
              </div>
            ) : (
              <div className="flex items-center gap-2 text-xs text-(--color-text-muted)">
                <Loader2 size={13} className="animate-spin text-(--color-accent)" />
                Waiting for the execution to register…
              </div>
            )
          ) : (
            <div className="space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p
                    className="truncate font-mono text-xs font-medium text-(--color-text)"
                    title={execution.definition_name}
                  >
                    {execution.definition_name}
                  </p>
                  <p className="mt-0.5 truncate text-[10px] text-(--color-text-subtle)">
                    {runningNode
                      ? `Now · ${runningNode.node_id}`
                      : `Execution · ${execution.id.slice(0, 8)}`}
                  </p>
                </div>
                <span className="shrink-0 rounded-md border border-(--color-border) bg-(--bg-page) px-2 py-1 text-[11px] font-medium">
                  <StatusBadge status={status} />
                </span>
              </div>

              <div className="grid grid-cols-3 divide-x divide-(--color-border) border-y border-(--color-border) py-2">
                <div className="pr-2">
                  <p className="text-[9px] font-semibold uppercase text-(--color-text-subtle)">Elapsed</p>
                  <p className="mt-0.5 font-mono text-[11px] text-(--color-text-2)">
                    {executionDuration(execution)}
                  </p>
                </div>
                <div className="px-2">
                  <p className="text-[9px] font-semibold uppercase text-(--color-text-subtle)">Nodes</p>
                  <p className="mt-0.5 font-mono text-[11px] text-(--color-text-2)">
                    {completedNodeCount} done · {nodeRuns.length} seen
                  </p>
                </div>
                <div className="pl-2">
                  <p className="text-[9px] font-semibold uppercase text-(--color-text-subtle)">Started</p>
                  <p className="mt-0.5 font-mono text-[11px] text-(--color-text-2)">
                    {new Date(execution.started_at).toLocaleTimeString([], {
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </p>
                </div>
              </div>

              {executionInputs.length > 0 && (
                <div className="flex flex-wrap gap-x-3 gap-y-1">
                  {executionInputs.map(([key, value]) => (
                    <span key={key} className="min-w-0 text-[10px] text-(--color-text-subtle)">
                      {key}{' '}
                      <strong className="font-mono font-medium text-(--color-text-2)">
                        {typeof value === 'string' ? value : JSON.stringify(value)}
                      </strong>
                    </span>
                  ))}
                </div>
              )}

              <div className="h-0.5 overflow-hidden rounded-full bg-(--color-border)">
                <div
                  className={cn(
                    'h-full rounded-full',
                    status === 'completed' && 'w-full bg-(--color-success)',
                    status === 'failed' && 'w-full bg-(--color-error)',
                    status === 'stopped' && 'w-full bg-(--color-text-muted)',
                    status === 'interrupted' && 'w-full bg-(--color-warning,orange)',
                    status === 'waiting_gate' &&
                      'w-3/5 animate-pulse bg-(--color-warning,orange)',
                    status === 'running' && 'w-2/5 animate-pulse bg-(--color-accent)',
                    status === 'done' && 'w-full bg-(--color-success)',
                  )}
                />
              </div>

              {execution.error && (
                <div className="flex gap-2 border-l-2 border-(--color-error) bg-(--color-error)/5 px-2.5 py-2">
                  <CircleX size={13} className="mt-0.5 shrink-0 text-(--color-error)" />
                  <p className="whitespace-pre-wrap text-[11px] leading-4 text-(--color-error)">
                    {execution.error}
                  </p>
                </div>
              )}
            </div>
          )}
        </section>

        {/* Inline gate — answer without a chat surface (spec §3.3). Rendered
            whenever the run is live: the execution row only says
            waiting_gate while the runner holds it in memory, so the gate is
            detected by polling pending questions, not by status alone. */}
        {active && (
          <div className="px-4 pt-3">
            <GateSection sessionId={sessionId} />
          </div>
        )}

        {/* Node-by-node progress + debug output. */}
        {nodeRuns.length > 0 && (
          <section className="border-b border-(--color-border) px-4 py-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="text-[10px] font-semibold uppercase text-(--color-text-subtle)">
                Node timeline
              </p>
              <span className="font-mono text-[10px] text-(--color-text-subtle)">
                {completedNodeCount}/{nodeRuns.length} settled
              </span>
            </div>
            <div className="relative ml-1 border-l border-(--color-border)">
              {nodeRuns.map((node) => (
                <NodeRunRow key={node.id} node={node} />
              ))}
            </div>
          </section>
        )}

        {/* What the agents are actually doing — read-only transcript tail. */}
        {sessionId.length > 0 && <ActivityLogSection sessionId={sessionId} active={active} />}

        {execution && !active && onDiscuss && (
          <div className="sticky bottom-0 border-t border-(--color-border) bg-(--bg-page)/95 p-3 backdrop-blur-sm">
            <Button size="sm" variant="secondary" onClick={onDiscuss} className="w-full">
              <MessageSquareText size={12} />
              Open Discussion
            </Button>
          </div>
        )}
      </div>
    </AimSidePanel>
  )
}

// ── Activity log ──────────────────────────────────────────────────────────────

/** Agent name rendered with design-system tokens only: the lead reads in
 * the accent color (same as active items everywhere else in the shell),
 * members read as regular emphasized text — identity comes from the name
 * itself, exactly like the real chat, not from invented colors. */
function AgentName({ agent }: { agent: string }) {
  return (
    <span
      className={cn(
        'font-semibold',
        agent === 'lead' ? 'text-(--color-accent)' : 'text-(--color-text-2)',
      )}
    >
      {agent}
    </span>
  )
}

/** Message body rendered as real markdown (headings, tables, code — the
 * lead's certify summaries are full markdown), collapsed to a faded
 * preview until clicked. line-clamp can't truncate nested block elements,
 * so the collapse is max-height + a bottom fade mask. */
function LogMarkdown({
  text,
  expanded,
  onToggle,
}: {
  text: string
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <div
      className={cn(
        'cursor-pointer overflow-hidden',
        !expanded &&
          'max-h-28 [mask-image:linear-gradient(to_bottom,black_65%,transparent)]',
      )}
      title="Click to expand / collapse"
      onClick={onToggle}
    >
      <div className="prose prose-sm max-w-none overflow-x-auto text-xs leading-4 text-(--color-text-2) [&_h1]:text-xs [&_h2]:text-xs [&_h3]:text-[11px] [&_h4]:text-[11px] [&_li]:my-0 [&_ol]:my-1 [&_p]:my-1 [&_pre]:my-1 [&_table]:my-1 [&_table]:text-[10px] [&_ul]:my-1">
        <MarkdownBlock content={text} />
      </div>
    </div>
  )
}

interface LogLine {
  key: string
  at: string
  agent: string
  kind: 'prompt' | 'say' | 'delegate' | 'handoff'
  text: string
  tools: string[]
  to?: string
  status?: string
}

function parseCallArgs(raw: unknown): Record<string, unknown> {
  if (typeof raw !== 'string') return {}
  try {
    const parsed = JSON.parse(raw)
    return typeof parsed === 'object' && parsed !== null ? parsed : {}
  } catch {
    return {}
  }
}

function snippet(value: unknown, max: number): string {
  const text = typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : ''
  return text.length > max ? `${text.slice(0, max)}…` : text
}

/** Like snippet() but newline-preserving — message bodies render as
 * markdown, so collapsing whitespace would destroy headings/tables. */
function clip(value: unknown, max: number): string {
  const text = typeof value === 'string' ? value.trim() : ''
  return text.length > max ? `${text.slice(0, max)}…` : text
}

/** The run's live transcript, laid out like a streaming chat: one block
 * per message with the agent's name + timestamp as a header, the text as
 * readable multi-line prose (click to expand long ones), tool calls as
 * their own sub-rows, and delegation/handoff rendered as explicit event
 * rows between blocks. Subagent activity is first-class — every agent
 * keeps a stable color across its dot, name, and message rail. Read-only
 * on purpose: chat stays post-run only (Discussion). */
function ActivityLogSection({ sessionId, active }: { sessionId: string; active: boolean }) {
  const historyQ = useQuery({
    queryKey: ['aim-monitor-history', sessionId],
    queryFn: () => teamHistory(sessionId),
    refetchInterval: active ? 4_000 : false,
  })
  const scrollRef = useRef<HTMLDivElement>(null)
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())

  const lines = useMemo<LogLine[]>(() => {
    const data = historyQ.data
    if (!data) return []
    const tagged: Array<{ agent: string; msg: MessageResponse }> = [
      ...data.lead.messages.map((msg) => ({ agent: 'lead', msg })),
      ...data.members.flatMap((member) =>
        member.messages.map((msg) => ({ agent: member.name, msg })),
      ),
    ]
    const out: LogLine[] = []
    for (const { agent, msg } of tagged) {
      if (msg.is_summary || msg.is_hidden || msg.role === 'tool') continue
      // A member session's user-role rows are the injected delegation brief —
      // already rendered as the lead's → line; repeating them as prompt
      // noise is what made subagent threads unreadable.
      if (msg.role === 'user' && agent !== 'lead') continue
      const at = msg.created_at ?? ''

      const plainTools: string[] = []
      for (const call of msg.tool_calls ?? []) {
        const name = call.function?.name
        if (!name) continue
        const args = parseCallArgs(call.function?.arguments)
        if (name === 'team_delegate') {
          out.push({
            key: `${msg.id}-${call.id}`,
            at,
            agent,
            kind: 'delegate',
            to: typeof args.to === 'string' ? args.to : '?',
            text: snippet(args.goal, 240),
            tools: [],
          })
        } else if (name === 'team_handoff') {
          out.push({
            key: `${msg.id}-${call.id}`,
            at,
            agent,
            kind: 'handoff',
            status: typeof args.status === 'string' ? args.status : undefined,
            text: clip(args.summary, 600),
            tools: [],
          })
        } else {
          plainTools.push(name)
        }
      }

      const text = clip(msg.content, 1200)
      if (text || plainTools.length > 0) {
        out.push({
          key: msg.id,
          at,
          agent,
          kind: msg.role === 'user' ? 'prompt' : 'say',
          text,
          tools: plainTools,
        })
      }
    }
    return out.sort((a, b) => a.at.localeCompare(b.at)).slice(-60)
  }, [historyQ.data])

  const agents = useMemo(
    () => [...new Set(lines.map((line) => line.agent))],
    [lines],
  )
  const lastAgent = lines.length > 0 ? lines[lines.length - 1].agent : null

  // Keep the newest message in view as the transcript grows.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines.length, active])

  if (historyQ.isLoading || lines.length === 0) return null

  const timeOf = (at: string): string => {
    const date = new Date(at)
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString()
  }

  const toggleExpand = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  return (
    <section className="px-4 py-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <div className="flex items-center gap-2">
          <p className="text-[10px] font-semibold uppercase text-(--color-text-subtle)">
            Event stream
          </p>
          <span className="rounded bg-(--bg-key) px-1.5 py-0.5 font-mono text-[9px] text-(--color-text-muted)">
            {lines.length}
          </span>
        </div>
        <span
          className="max-w-52 truncate text-[10px] text-(--color-text-subtle)"
          title={agents.join(' · ')}
        >
          {agents.join(' · ')}
        </span>
      </div>

      <div className="overflow-hidden rounded-md border border-(--color-border) bg-(--bg-subtle)/30">
        <div ref={scrollRef} className="relative min-h-64 max-h-[52vh] overflow-y-auto px-3">
          <div
            className="absolute bottom-0 left-[22px] top-0 w-px bg-(--color-border)"
            aria-hidden="true"
          />
        {lines.map((line) => {
          if (line.kind === 'delegate') {
            return (
              <div
                key={line.key}
                className="relative flex gap-3 border-b border-(--color-border)/60 py-2.5 pl-1"
              >
                <span className="relative z-[1] flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-(--color-border) bg-(--bg-page) text-(--color-text-muted)">
                  <Shuffle size={10} aria-hidden="true" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-1.5 text-[10px] text-(--color-text-subtle)">
                    <AgentName agent={line.agent} />
                    <ArrowRight size={9} aria-hidden="true" />
                    <AgentName agent={line.to ?? '?'} />
                    {line.at && <span className="ml-auto font-mono">{timeOf(line.at)}</span>}
                  </p>
                  {line.text && (
                    <p
                      className="mt-0.5 truncate text-[11px] text-(--color-text-muted)"
                      title={line.text}
                    >
                      {line.text}
                    </p>
                  )}
                </div>
              </div>
            )
          }

          if (line.kind === 'handoff') {
            return (
              <div
                key={line.key}
                className="relative flex gap-3 border-b border-(--color-border)/60 py-2.5 pl-1"
              >
                <span className="relative z-[1] flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-(--color-accent)/40 bg-(--bg-page) text-(--color-accent)">
                  <CornerDownLeft size={10} aria-hidden="true" />
                </span>
                <div className="min-w-0 flex-1 border-l-2 border-(--color-accent)/40 pl-2.5">
                  <p className="mb-0.5 flex items-center gap-1.5 text-[10px]">
                    <span className="font-semibold text-(--color-text-2)">
                      Handoff · {line.agent}
                    </span>
                    {line.status && (
                      <span className="rounded bg-(--bg-key) px-1 py-px text-[9px] text-(--color-text-muted)">
                        {line.status}
                      </span>
                    )}
                    {line.at && (
                      <span className="ml-auto font-mono text-(--color-text-subtle)">
                        {timeOf(line.at)}
                      </span>
                    )}
                  </p>
                  {line.text && (
                    <LogMarkdown
                      text={line.text}
                      expanded={expanded.has(line.key)}
                      onToggle={() => toggleExpand(line.key)}
                    />
                  )}
                </div>
              </div>
            )
          }

          if (line.kind === 'prompt') {
            return (
              <div
                key={line.key}
                className="relative flex gap-3 border-b border-(--color-border)/60 py-2.5 pl-1"
              >
                <span className="relative z-[1] flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-(--color-border) bg-(--bg-page) text-(--color-text-muted)">
                  <FileText size={10} aria-hidden="true" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="mb-0.5 flex items-center gap-2 text-[10px] text-(--color-text-subtle)">
                    <span className="font-semibold uppercase">Run brief</span>
                    {line.at && <span className="ml-auto font-mono">{timeOf(line.at)}</span>}
                  </p>
                  <p
                    className={cn(
                      'cursor-pointer whitespace-pre-wrap text-[11px] leading-4 text-(--color-text-muted)',
                      !expanded.has(line.key) && 'line-clamp-3',
                    )}
                    title="Click to expand / collapse"
                    onClick={() => toggleExpand(line.key)}
                  >
                    {line.text}
                  </p>
                </div>
              </div>
            )
          }

          return (
            <div
              key={line.key}
              className="relative flex gap-3 border-b border-(--color-border)/60 py-2.5 pl-1"
            >
              <span className="relative z-[1] flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-(--color-border) bg-(--bg-page) text-(--color-text-muted)">
                <Bot size={10} aria-hidden="true" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="mb-0.5 flex items-center gap-2 text-[10px]">
                  <AgentName agent={line.agent} />
                  {line.at && (
                    <span className="ml-auto font-mono text-(--color-text-subtle)">
                      {timeOf(line.at)}
                    </span>
                  )}
                </p>
                {line.text && (
                  <LogMarkdown
                    text={line.text}
                    expanded={expanded.has(line.key)}
                    onToggle={() => toggleExpand(line.key)}
                  />
                )}
                {line.tools.length > 0 && (
                  <p className={cn('flex flex-wrap items-center gap-1', line.text && 'mt-1')}>
                    {line.tools.map((tool, index) => (
                      <span
                        key={`${line.key}-${tool}-${index}`}
                        className="flex items-center gap-1 rounded border border-(--color-border)/70 bg-(--bg-page) px-1.5 py-0.5 font-mono text-[9px] text-(--color-text-muted)"
                      >
                        <Wrench size={9} aria-hidden="true" />
                        {tool}
                      </span>
                    ))}
                  </p>
                )}
              </div>
            </div>
          )
        })}
        </div>

        {active && (
          <div className="flex h-9 items-center gap-2 border-t border-(--color-border) bg-(--bg-page) px-3 text-[10px] text-(--color-text-subtle)">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-(--color-accent) opacity-40" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-(--color-accent)" />
            </span>
            {lastAgent ? (
              <>
                <AgentName agent={lastAgent} />
                <span>is working</span>
              </>
            ) : (
              <span>Waiting for activity</span>
            )}
            <span className="ml-auto font-mono">live</span>
          </div>
        )}
      </div>
    </section>
  )
}

function NodeRunRow({ node }: { node: WorkflowNodeRun }) {
  const [open, setOpen] = useState(false)
  const hasDetail = Boolean(node.error) || Boolean(node.output && Object.keys(node.output).length)
  const duration = node.ended_at
    ? `${Math.max(0, (new Date(node.ended_at).getTime() - new Date(node.started_at).getTime()) / 1000).toFixed(1)}s`
    : null

  return (
    <div className="relative pl-5">
      <span className="absolute -left-[6px] top-2.5 z-[1] flex h-3 w-3 items-center justify-center rounded-full bg-(--bg-page)">
        <NodeStatusIcon status={node.status} />
      </span>
      <button
        type="button"
        onClick={() => hasDetail && setOpen((v) => !v)}
        className={cn(
          'flex min-h-8 w-full items-center gap-1.5 rounded px-1.5 text-left text-xs',
          hasDetail && 'hover:bg-(--bg-key)',
        )}
      >
        {hasDetail ? (
          open ? (
            <ChevronDown size={10} className="shrink-0 text-(--color-text-subtle)" />
          ) : (
            <ChevronRight size={10} className="shrink-0 text-(--color-text-subtle)" />
          )
        ) : (
          <span className="w-2.5 shrink-0" />
        )}
        <span className="min-w-0 flex-1 truncate font-mono text-(--color-text-2)">
          {node.node_id}
          {node.iteration !== null && (
            <span className="text-(--color-text-subtle)"> #{node.iteration}</span>
          )}
        </span>
        {duration && (
          <span className="shrink-0 text-[10px] text-(--color-text-subtle)">{duration}</span>
        )}
        <span className="shrink-0 text-[9px] uppercase text-(--color-text-subtle)">
          {node.status}
        </span>
      </button>
      {open && (
        <div className="mb-2 space-y-1 border-l-2 border-(--color-border) bg-(--bg-subtle)/50 px-2.5 py-2">
          {node.error && (
            <p className="whitespace-pre-wrap text-[11px] text-(--color-error)">{node.error}</p>
          )}
          {node.output && Object.keys(node.output).length > 0 && (
            <pre className="max-h-56 overflow-auto rounded bg-(--bg-key) p-2 font-mono text-[10px] leading-4 text-(--color-text-2)">
              {JSON.stringify(node.output, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

function GateSection({ sessionId }: { sessionId: string }) {
  const queryClient = useQueryClient()
  const [replying, setReplying] = useState(false)
  const [freeText, setFreeText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const pendingQ = useQuery({
    queryKey: ['aim-pending-questions', sessionId],
    queryFn: () => getPendingQuestions(sessionId),
    refetchInterval: 3_000,
  })
  const batch = pendingQ.data?.questions[0]
  const item = batch?.items[0]
  const formattedQuestion = item ? formatApprovalQuestion(item.question) : ''

  const answer = async (value: string) => {
    if (!batch) return
    setReplying(true)
    setError(null)
    try {
      await replyAskUserQuestion(sessionId, batch.request_id, [value])
      void queryClient.invalidateQueries({ queryKey: ['aim-pending-questions', sessionId] })
    } catch (err) {
      // The backend rejects an off-menu answer to a gate (strict choices) or
      // an already-resolved request — surface it instead of silently
      // re-enabling the buttons.
      setError(err instanceof Error ? err.message : 'Failed to submit your answer.')
    } finally {
      setReplying(false)
    }
  }

  // Quiet until a question is actually pending — the section polls in the
  // background and materializes the amber box only when the run needs you.
  if (!item) return null

  return (
    <div className="space-y-2 rounded-md border border-(--color-warning,orange)/40 bg-(--bg-key) px-3 py-2">
      <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-(--color-warning,orange)">
        <CirclePause size={11} />
        Waiting for you
      </p>
      <div className="max-h-96 overflow-auto text-xs leading-5 text-(--color-text)">
        <MarkdownBlock content={formattedQuestion} sessionId={sessionId} />
      </div>
      {item.options.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {item.options.map((option) => (
            <Button
              key={option}
              size="sm"
              variant="secondary"
              disabled={replying}
              onClick={() => void answer(option)}
            >
              {option}
            </Button>
          ))}
        </div>
      ) : (
        <div className="flex gap-2">
          <input
            type="text"
            value={freeText}
            onChange={(e) => setFreeText(e.target.value)}
            placeholder="Your answer…"
            className="flex-1 rounded-md border border-(--color-border) bg-(--bg-subtle) px-2 py-1.5 text-xs text-(--color-text)"
          />
          <Button
            size="sm"
            disabled={replying || !freeText.trim()}
            onClick={() => void answer(freeText.trim())}
          >
            Send
          </Button>
        </div>
      )}
      {error && (
        <p className="text-[11px] leading-4 text-(--color-danger,red)">{error}</p>
      )}
    </div>
  )
}

// ── Row bits ──────────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: RunDisplayStatus }) {
  switch (status) {
    case 'running':
      return (
        <span className="inline-flex items-center gap-1 text-(--color-accent)">
          <Loader2 size={11} className="animate-spin" /> running
        </span>
      )
    case 'waiting_gate':
      return (
        <span className="inline-flex items-center gap-1 text-(--color-warning,orange)">
          <CirclePause size={11} /> needs input
        </span>
      )
    case 'completed':
      return (
        <span className="inline-flex items-center gap-1 text-(--color-success)">
          <CircleCheck size={11} /> pass
        </span>
      )
    case 'failed':
      return (
        <span className="inline-flex items-center gap-1 text-(--color-error)">
          <CircleX size={11} /> fail
        </span>
      )
    case 'stopped':
      return (
        <span className="inline-flex items-center gap-1 text-(--color-text-muted)">
          <OctagonX size={11} /> stopped
        </span>
      )
    case 'interrupted':
      return (
        <span
          className="inline-flex items-center gap-1 text-(--color-text-muted)"
          title="The backend restarted while this run was active — its final state was lost."
        >
          <CircleAlert size={11} /> interrupted
        </span>
      )
    case 'done':
      return (
        <span className="inline-flex items-center gap-1 text-(--color-text-muted)">
          <CircleCheck size={11} className="text-(--color-success)" /> done
        </span>
      )
  }
}

function NodeStatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'succeeded':
      return <CircleCheck size={11} className="shrink-0 text-(--color-success)" />
    case 'failed':
      return <CircleX size={11} className="shrink-0 text-(--color-error)" />
    case 'running':
      return <Loader2 size={11} className="shrink-0 animate-spin text-(--color-accent)" />
    case 'skipped':
      return <CircleDashed size={11} className="shrink-0 text-(--color-text-subtle)" />
    default:
      return <CircleDashed size={11} className="shrink-0 text-(--color-text-subtle)" />
  }
}

/** The domain-level compare/convert/test verdict, distinct from the
 * workflow's own running/pass/fail status — a pipeline can complete
 * successfully while its compare verdict is `fail` (that's exactly why
 * aim-test-compare has a certify/triage gate). Shown as a small chip
 * next to StatusBadge, not folded into it. */
function VerdictChip({ verdict }: { verdict: string }) {
  const tone =
    verdict === 'pass'
      ? 'text-(--color-success)'
      : verdict === 'acceptable_diff'
        ? 'text-(--color-warning,orange)'
        : 'text-(--color-error)'
  const Icon = verdict === 'pass' || verdict === 'acceptable_diff' ? CircleCheck : CircleX
  return (
    <span className={cn('inline-flex items-center gap-0.5', tone)} title={`Verdict: ${verdict}`}>
      <Icon size={10} />
      {verdict}
    </span>
  )
}

function RunRow({
  run,
  execution,
  aimRun,
  monitorOpen,
  reportOpen,
  discussionOpen,
  onMonitor,
  onReport,
  onDiscuss,
  onRetry,
}: {
  run: SessionResponse
  execution?: WorkflowExecutionSummary
  /** The linked aim_runs verdict/report, when this session produced one. */
  aimRun?: AimRunListItem
  monitorOpen: boolean
  reportOpen: boolean
  discussionOpen: boolean
  onMonitor: () => void
  onReport: () => void
  onDiscuss: () => void
  onRetry: () => void
}) {
  const status = displayStatus(Boolean(run.running), execution)
  const finished = !(status === 'running' || status === 'waiting_gate')
  const retryable =
    Boolean(execution) &&
    (status === 'failed' ||
      status === 'interrupted' ||
      status === 'stopped' ||
      aimRun?.verdict === 'fail' ||
      aimRun?.verdict === 'error')
  const selected = monitorOpen || reportOpen || discussionOpen
  const pipelineName = execution?.definition_name ?? 'No workflow execution'
  return (
    <tr
      className={cn(
        'group h-[58px] border-t border-(--color-border) transition-colors first:border-t-0',
        selected
          ? 'bg-(--bg-key)/80'
          : status === 'running' || status === 'waiting_gate'
            ? 'bg-(--color-accent)/[0.025] hover:bg-(--bg-subtle)/55'
            : 'hover:bg-(--bg-subtle)/55',
      )}
    >
      <td className="px-3 py-2" title={run.title ?? run.id}>
        <div className="flex min-w-0 items-center gap-2.5">
          <span
            className={cn(
              'flex h-7 w-7 shrink-0 items-center justify-center rounded-md border bg-(--bg-page)',
              status === 'running' && 'border-(--color-accent)/30 text-(--color-accent)',
              status === 'waiting_gate' &&
                'border-(--color-warning,orange)/35 text-(--color-warning,orange)',
              status === 'failed' && 'border-(--color-error)/30 text-(--color-error)',
              status === 'completed' && 'border-(--color-success)/30 text-(--color-success)',
              !['running', 'waiting_gate', 'failed', 'completed'].includes(status) &&
                'border-(--color-border) text-(--color-text-muted)',
            )}
          >
            {status === 'running' ? (
              <Loader2 size={12} className="animate-spin" />
            ) : status === 'waiting_gate' ? (
              <CirclePause size={12} />
            ) : status === 'failed' ? (
              <CircleX size={12} />
            ) : (
              <Shuffle size={12} />
            )}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[12px] font-medium text-(--color-text)">
              {run.title ?? run.id.slice(0, 8)}
            </p>
            <p className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[9px] text-(--color-text-subtle)">
              <span className="truncate font-mono" title={pipelineName}>
                {pipelineName}
              </span>
              <span aria-hidden="true">·</span>
              <span className="shrink-0 font-mono">{run.id.slice(0, 8)}</span>
              {execution?.retry_of_execution_id && (
                <span className="shrink-0 rounded bg-(--bg-key) px-1 py-px uppercase">
                  retry
                </span>
              )}
            </p>
          </div>
        </div>
      </td>
      <td className="px-2 py-2" title={execution?.error ?? undefined}>
        <div className="flex flex-col items-start gap-1">
          <RunStatusPill status={status} />
          {aimRun && <VerdictChip verdict={aimRun.verdict} />}
        </div>
      </td>
      <td
        className="px-2 py-2 text-[10px] text-(--color-text-muted)"
        title={run.created_at ? new Date(run.created_at).toLocaleString() : undefined}
      >
        {formatRelativeDate(run.created_at)}
      </td>
      <td className="px-2 py-2 font-mono text-[10px] text-(--color-text-muted)">
        <span className="rounded bg-(--bg-subtle)/65 px-1.5 py-1">
          {executionDuration(execution)}
        </span>
      </td>
      <td className="px-2 py-2 text-right">
        <span className="inline-flex items-center rounded-md border border-(--color-border) bg-(--bg-page) p-0.5 shadow-sm opacity-80 transition-opacity group-hover:opacity-100">
          <button
            type="button"
            onClick={onMonitor}
            aria-label={status === 'waiting_gate' ? 'Answer pending gate' : 'Open run monitor'}
            aria-pressed={monitorOpen}
            className={cn(
              'flex h-7 w-7 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)',
              monitorOpen
                ? 'bg-(--bg-key) text-(--color-accent)'
                : status === 'waiting_gate'
                  ? 'text-(--color-warning,orange)'
                  : '',
            )}
            title="Node progress, per-node log, and the gate if one is waiting"
          >
            {status === 'waiting_gate' ? <CirclePause size={11} /> : <Activity size={11} />}
          </button>
          {aimRun && (
            <button
              type="button"
              onClick={onReport}
              aria-label="Open run report"
              aria-pressed={reportOpen}
              className={cn(
                'flex h-7 w-7 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)',
                reportOpen
                  ? 'bg-(--bg-key) text-(--color-accent)'
                  : '',
              )}
              title="Verdict, stats, and the full report for this run"
            >
              <FileText size={11} />
            </button>
          )}
          {retryable && (
            <button
              type="button"
              onClick={onRetry}
              aria-label="Retry pipeline with the same inputs"
              className="flex h-7 w-7 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
              title="Retry with the same inputs as a linked new attempt"
            >
              <Repeat size={11} />
            </button>
          )}
          {finished && (
            <button
              type="button"
              onClick={onDiscuss}
              aria-label="Open run discussion"
              aria-pressed={discussionOpen}
              className={cn(
                'flex h-7 w-7 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)',
                discussionOpen
                  ? 'bg-(--bg-key) text-(--color-accent)'
                  : '',
              )}
              title="Open this run's transcript (post-run only)"
            >
              <MessageSquareText size={11} />
            </button>
          )}
        </span>
      </td>
    </tr>
  )
}

function RunStatusPill({ status }: { status: RunDisplayStatus }) {
  return (
    <span
      className={cn(
        'inline-flex min-w-[82px] items-center justify-center rounded-md border px-1.5 py-1 text-[10px] font-medium',
        status === 'running' && 'border-(--color-accent)/25 bg-(--color-accent)/5',
        status === 'waiting_gate' &&
          'border-(--color-warning,orange)/30 bg-(--color-warning,orange)/5',
        status === 'completed' &&
          'border-(--color-success)/25 bg-(--color-success)/5',
        status === 'failed' && 'border-(--color-error)/25 bg-(--color-error)/5',
        (status === 'stopped' || status === 'done') &&
          'border-(--color-border) bg-(--bg-subtle)/55',
        status === 'interrupted' &&
          'border-(--color-warning,orange)/25 bg-(--color-warning,orange)/5',
      )}
    >
      <StatusBadge status={status} />
    </span>
  )
}

// ── Report panel (Runs & Reports, folded in) ─────────────────────────────────

/** The aim_runs verdict + stats + full report.json for one run — what
 * used to be Runs & Reports' right column, now a side panel matching
 * Monitor/Discussion. Self-fetches from just a runId, so it works both
 * from a table row (which knows the summary already) and from the
 * /aim/$projectId/runs/$runId deep link (which only has the id). */
function ReportPanel({
  projectId,
  runId,
  title,
  onClose,
  onOpenNodes,
}: {
  projectId: string
  runId: string
  title?: string
  onClose: () => void
  onOpenNodes: (sessionId: string) => void
}) {
  const detailQuery = useQuery({
    queryKey: queryKeys.projects.aimRun(projectId, runId),
    queryFn: () => getAimRun(projectId, runId),
  })
  const detail = detailQuery.data
  const resolvedTitle = title ?? (detail ? `${detail.kind} · ${runId.slice(0, 8)}` : runId.slice(0, 8))

  return (
    <AimSidePanel storageKey={STORAGE_KEYS.panels.aimReport} defaultWidth={420}>
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-(--color-border) px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-(--color-text)">Report</h2>
          <p className="mt-0.5 truncate text-xs text-(--color-text-subtle)">
            {resolvedTitle}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close report"
          title="Close"
          className="rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
        >
          <X size={16} />
        </button>
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {detailQuery.isLoading ? (
          <p className="flex items-center gap-1.5 text-xs text-(--color-text-subtle)">
            <Loader2 size={12} className="animate-spin" /> Loading report…
          </p>
        ) : detailQuery.isError || !detail ? (
          <p className="text-xs text-(--color-error)">Failed to load the run.</p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span
                className={cn(
                  'rounded px-2 py-0.5 text-xs font-medium',
                  detail.verdict === 'pass'
                    ? 'bg-(--color-success-bg,var(--bg-key)) text-(--color-success,inherit)'
                    : detail.verdict === 'acceptable_diff'
                      ? 'bg-(--bg-key) text-(--color-warning,orange)'
                      : 'bg-(--color-error-subtle,var(--bg-key)) text-(--color-error)',
                )}
              >
                {detail.verdict}
              </span>
              <span className="text-xs text-(--color-text-muted)">
                {detail.kind}
                {detail.case_set ? ` · ${detail.case_set}` : ''}
              </span>
              {(detail.workflow_execution_id || detail.session_id) && (
                <button
                  type="button"
                  onClick={() => detail.session_id && onOpenNodes(detail.session_id)}
                  className="ml-auto flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium text-(--color-text-muted) transition-colors hover:text-(--color-text)"
                  title="This run's workflow nodes and per-node log"
                >
                  <Activity size={12} />
                  Nodes
                </button>
              )}
            </div>
            {Object.keys(detail.stats ?? {}).length > 0 && (
              <div className="flex flex-wrap gap-2">
                {Object.entries(detail.stats).map(([key, value]) => (
                  <div key={key} className="rounded bg-(--bg-key) px-2.5 py-1.5">
                    <p className="text-[10px] text-(--color-text-subtle)">{key}</p>
                    <p className="text-xs font-medium text-(--color-text)">{String(value)}</p>
                  </div>
                ))}
              </div>
            )}
            {detail.report ? (
              <pre className="overflow-x-auto rounded bg-(--bg-key) p-3 font-mono text-[11px] leading-4 text-(--color-text-2)">
                {JSON.stringify(detail.report, null, 2)}
              </pre>
            ) : (
              <p className="text-xs text-(--color-text-subtle)">
                No report file on this machine
                {detail.report_path ? ` (${detail.report_path})` : ''}.
              </p>
            )}
          </>
        )}
      </div>
    </AimSidePanel>
  )
}
