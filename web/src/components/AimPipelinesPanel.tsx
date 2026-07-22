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
  MessageSquareText,
  OctagonX,
  Play,
  Repeat,
  ShieldCheck,
  Shuffle,
  Wrench,
  X,
} from 'lucide-react'
import {
  approveWorkflow,
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
import { formatRelativeDate } from '@/utils/format'
import { takeAimPipelinePrefill } from '@/lib/aimHandoff'
import { cn } from '@/lib/utils'
import type {
  AimRunListItem,
  AimUnitOut,
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
}: {
  spec: WorkflowInputSpec
  value: unknown
  onChange: (value: unknown) => void
  unitOptions: { key: string; phase: string }[]
}) {
  const label = spec.name
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')

  if (spec.name === 'unit') {
    return (
      <label className="flex min-w-48 flex-col gap-1 text-xs text-(--color-text-muted)">
        {label}
        {unitOptions.length > 0 ? (
          <Combobox
            size="sm"
            value={(value as string) || null}
            onValueChange={(v) => onChange(v ?? '')}
            items={unitOptions.map((unit) => ({
              value: unit.key,
              label: `${unit.key} · ${unit.phase}`,
            }))}
            placeholder="Select a unit…"
            emptyText="No unit matches."
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

  if (spec.type === 'enum') {
    return (
      <label className="flex flex-col gap-1 text-xs text-(--color-text-muted)">
        {label}
        <select
          value={(value as string) ?? spec.default ?? spec.options?.[0] ?? ''}
          onChange={(e) => onChange(e.target.value)}
          className="rounded-md border border-(--color-border) bg-(--bg-subtle) px-2 py-1.5 text-xs text-(--color-text)"
        >
          {(spec.options ?? []).map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
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

  // The pipeline picker is every discovered scope="aim" workflow — the 6
  // builtin ones plus anything a rulebook's own workflows/ directory
  // installed (rulebook_install.py copies those into the same global
  // discovery root, so they show up here with zero special-casing).
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
  const [inputValues, setInputValues] = useState<Record<string, unknown>>(() => ({
    unit: prefill?.unit ?? '',
    wave: prefill?.wave != null ? String(prefill.wave) : '',
  }))
  const setInputValue = useCallback((name: string, value: unknown) => {
    setInputValues((prev) => ({ ...prev, [name]: value }))
  }, [])

  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
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
        .map((u) => ({ key: `${u.module}/${u.name}`, phase: u.phase }))
        .sort((a, b) => a.key.localeCompare(b.key)),
    [units],
  )

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
    (selectedWorkflow?.inputs ?? []).every((spec) => {
      if (!spec.required) return true
      const value = inputValues[spec.name]
      return value !== undefined && value !== null && value !== ''
    })

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
  }, [selectedWorkflow, targetWorkspace, project.id, buildInputs, runLabel, queryClient])

  // §9.3: convert pipelines write to the target repo — require explicit confirm.
  const handleRun = useCallback(() => {
    if (selectedWorkflow && CONVERT_WORKFLOW_NAMES.has(selectedWorkflow.name)) {
      setConfirmOpen(true)
    } else {
      void doRun()
    }
  }, [selectedWorkflow, doRun])

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
          <label className="flex flex-col gap-1 text-xs text-(--color-text-muted)">
            Pipeline
            <Combobox
              size="sm"
              value={pipelineName}
              onValueChange={setPipelineName}
              items={aimWorkflows.map((wf) => ({
                value: wf.name,
                label: pipelineDisplayName(wf.name),
              }))}
              placeholder={workflowsQ.isLoading ? 'Loading…' : 'Select a pipeline…'}
              emptyText="No pipelines found."
              className="min-w-44"
            />
          </label>
          {(selectedWorkflow?.inputs ?? []).map((spec) => (
            <WorkflowInputField
              key={spec.name}
              spec={spec}
              value={inputValues[spec.name]}
              onChange={(value) => setInputValue(spec.name, value)}
              unitOptions={unitOptions}
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
          units={units}
          wave={
            typeof inputValues.wave === 'string' && inputValues.wave !== ''
              ? Number(inputValues.wave)
              : null
          }
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
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="text-[10px] uppercase text-(--color-text-subtle)">
                  <th className="pb-2 font-medium">Run</th>
                  <th className="pb-2 font-medium">Pipeline</th>
                  <th className="pb-2 font-medium">Status</th>
                  <th className="pb-2 font-medium">Started</th>
                  <th className="pb-2 font-medium">Took</th>
                  <th className="pb-2" />
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
                        setMonitorSession((prev) => (prev?.id === run.id ? null : run))
                      }}
                      onReport={() => {
                        if (!aimRun) return
                        setMonitorSession(null)
                        setDiscussion(null)
                        setReportRun((prev) =>
                          prev?.runId === aimRun.id
                            ? null
                            : { runId: aimRun.id, title: `${aimRun.unit} · ${aimRun.kind}` },
                        )
                      }}
                      onDiscuss={() => {
                        setMonitorSession(null)
                        setReportRun(null)
                        setDiscussion((prev) => (prev?.id === run.id ? null : run))
                      }}
                    />
                  )
                })}
              </tbody>
            </table>
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
          <div className="flex items-center justify-between gap-2 border-b border-(--color-border) px-3 py-2">
            <p className="min-w-0 truncate text-xs font-medium text-(--color-text)">
              Discussion
              <span className="ml-1.5 font-normal text-(--color-text-subtle)">
                {discussion.title ?? discussion.id.slice(0, 8)}
              </span>
            </p>
            <button
              type="button"
              onClick={() => setDiscussion(null)}
              aria-label="Close discussion"
              className="shrink-0 rounded p-0.5 text-(--color-text-muted) hover:text-(--color-text)"
            >
              <X size={13} />
            </button>
          </div>
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
      return <Bot size={11} className="shrink-0 text-(--color-accent)" />
    case 'gate':
    case 'input':
      return <CirclePause size={11} className="shrink-0 text-(--color-warning,orange)" />
    case 'tool':
      return <Wrench size={11} className="shrink-0 text-(--color-text-subtle)" />
    case 'foreach':
      return <Repeat size={11} className="shrink-0 text-(--color-text-subtle)" />
    case 'notify':
      return <Bell size={11} className="shrink-0 text-(--color-text-subtle)" />
    default:
      return <Shuffle size={11} className="shrink-0 text-(--color-text-subtle)" />
  }
}

/** Readiness line: which units the selected pipeline can actually act on
 * right now — surfaced up front so an empty wave or a phase gap is visible
 * before hitting Run, not after a confusing no-op. Hand-written per builtin
 * pipeline (there's no generic way to know what an arbitrary custom
 * rulebook workflow reads/writes); a workflow name that doesn't match one
 * of these six falls through to `null` — no hint shown, not an error. */
function eligibility(
  workflowName: string,
  units: AimUnitOut[],
  wave: number | null,
): { text: string; warn: boolean } | null {
  const count = (phase: string, w?: number | null) =>
    units.filter((u) => u.phase === phase && (w == null || u.wave === w)).length
  switch (workflowName) {
    case 'aim-assess':
      return {
        text:
          units.length === 0
            ? 'Builds the unit inventory from the source estate — the KB has no units yet.'
            : `Refreshes the inventory — ${units.length} unit(s) currently indexed.`,
        warn: false,
      }
    case 'aim-understand': {
      const n = count('inventory')
      return {
        text: `${n} unit(s) at phase inventory await documentation.`,
        warn: n === 0 && units.length > 0,
      }
    }
    case 'aim-convert-unit': {
      const n = count('designed')
      return {
        text: `${n} unit(s) at phase designed (plan → gate → implement; the plan step designs first if needed).`,
        warn: false,
      }
    }
    case 'aim-convert-wave': {
      if (wave == null || Number.isNaN(wave)) return null
      const n = count('designed', wave)
      return {
        text:
          n === 0
            ? `No designed unit(s) in wave ${wave} — this pipeline selects by phase=designed; run aim-convert-unit's plan step (or aim-understand) first.`
            : `${n} designed unit(s) in wave ${wave} will be converted sequentially.`,
        warn: n === 0,
      }
    }
    case 'aim-test-compare': {
      const n = count('converted')
      return {
        text: `${n} unit(s) at phase converted awaiting an equivalence verdict.`,
        warn: false,
      }
    }
    case 'aim-cutover-check': {
      if (wave == null || Number.isNaN(wave)) return null
      const eq = count('equivalent', wave)
      const total = units.filter((u) => u.wave === wave).length
      return {
        text: `${eq} of ${total} unit(s) in wave ${wave} are certified equivalent.`,
        warn: total > 0 && eq < total,
      }
    }
    default:
      return null
  }
}

function PipelineInfoCard({
  workflow,
  graph,
  units,
  wave,
}: {
  workflow: WorkflowListItem | undefined
  graph: Record<string, unknown> | undefined
  units: AimUnitOut[]
  wave: number | null
}) {
  if (!workflow) return null
  const nodes = Array.isArray(graph?.nodes)
    ? (graph.nodes as Array<{ id?: string; kind?: string }>).filter(
        (n) => typeof n?.id === 'string' && typeof n?.kind === 'string',
      )
    : []
  const gateCount = nodes.filter((n) => n.kind === 'gate' || n.kind === 'input').length
  const hint = eligibility(workflow.name, units, wave)

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

      {/* Node chain — declared order; gates in amber. */}
      {nodes.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          {nodes.map((node, index) => (
            <span key={node.id} className="flex items-center gap-1">
              {index > 0 && (
                <ArrowRight size={10} className="text-(--color-text-subtle)" aria-hidden="true" />
              )}
              <span
                className={cn(
                  'flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[10px]',
                  node.kind === 'gate' || node.kind === 'input'
                    ? 'border-(--color-warning,orange)/40 text-(--color-warning,orange)'
                    : 'border-(--color-border) text-(--color-text-2)',
                )}
                title={`${node.kind} node`}
              >
                <NodeKindIcon kind={node.kind as string} />
                {node.id}
              </span>
            </span>
          ))}
        </div>
      )}

      {/* Inputs + readiness */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {workflow.inputs.length > 0 && (
          <span className="flex items-center gap-1.5 text-[11px] text-(--color-text-subtle)">
            inputs:
            {workflow.inputs.map((input) => (
              <span key={input.name} className="rounded bg-(--bg-key) px-1.5 py-0.5 font-mono text-[10px] text-(--color-text-2)">
                {input.name}: {input.type}
                {input.required ? '' : '?'}
              </span>
            ))}
          </span>
        )}
        {!workflow.valid && (
          <span className="text-[11px] text-(--color-error)" title={workflow.errors.join('\n')}>
            definition invalid — {workflow.errors[0] ?? 'see errors'}
          </span>
        )}
      </div>
      {hint && (
        <p
          className={cn(
            'text-[11px]',
            hint.warn ? 'text-(--color-warning,orange)' : 'text-(--color-text-subtle)',
          )}
        >
          {hint.text}
        </p>
      )}
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
    <AimSidePanel storageKey={STORAGE_KEYS.panels.aimMonitor} defaultWidth={420}>
      <div className="flex items-center justify-between gap-2 border-b border-(--color-border) px-3 py-2">
        <p className="min-w-0 truncate text-xs font-medium text-(--color-text)">
          Run monitor
          <span className="ml-1.5 font-normal text-(--color-text-subtle)">
            {title ?? sessionId.slice(0, 8)}
          </span>
        </p>
        <div className="flex shrink-0 items-center gap-1">
          {active && executionId && (
            <button
              type="button"
              onClick={() => void stop()}
              disabled={stopping}
              className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-(--color-error) transition-colors hover:bg-(--bg-key)"
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
            className="rounded p-0.5 text-(--color-text-muted) hover:text-(--color-text)"
          >
            <X size={13} />
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {/* Execution summary */}
        {!execution ? (
          lookupExhausted ? (
            <p className="text-xs text-(--color-text-subtle)">
              No workflow execution is recorded for this run.
            </p>
          ) : (
            <p className="flex items-center gap-1.5 text-xs text-(--color-text-subtle)">
              <Loader2 size={12} className="animate-spin" />
              Waiting for the execution to register…
            </p>
          )
        ) : (
          <div className="space-y-1 rounded-md bg-(--bg-key) px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate font-mono text-[11px] text-(--color-text-2)">
                {execution.definition_name}
              </span>
              <StatusBadge status={status} />
            </div>
            <p className="text-[10px] text-(--color-text-subtle)">
              started {new Date(execution.started_at).toLocaleTimeString()}
              {execution.ended_at
                ? ` · finished ${new Date(execution.ended_at).toLocaleTimeString()}`
                : ''}
            </p>
            {execution.error && (
              <p className="whitespace-pre-wrap text-[11px] text-(--color-error)">
                {execution.error}
              </p>
            )}
          </div>
        )}

        {/* Inline gate — answer without a chat surface (spec §3.3). Rendered
            whenever the run is live: the execution row only says
            waiting_gate while the runner holds it in memory, so the gate is
            detected by polling pending questions, not by status alone. */}
        {active && <GateSection sessionId={sessionId} />}

        {/* Node-by-node progress + debug output. */}
        {nodeRuns.length > 0 && (
          <div>
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">
              Nodes · {nodeRuns.filter((n) => n.status === 'succeeded').length}/{nodeRuns.length}
            </p>
            <div className="space-y-0.5">
              {nodeRuns.map((node) => (
                <NodeRunRow key={node.id} node={node} />
              ))}
            </div>
          </div>
        )}

        {/* What the agents are actually doing — read-only transcript tail. */}
        {sessionId.length > 0 && <ActivityLogSection sessionId={sessionId} active={active} />}

        {execution && !active && onDiscuss && (
          <Button size="sm" variant="secondary" onClick={onDiscuss} className="w-full">
            <MessageSquareText size={12} />
            Open Discussion
          </Button>
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
        'font-semibold tracking-wide',
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
    <div>
      <div className="mb-1 flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">
          Activity log
        </p>
        {/* Who's on this run. */}
        <span className="text-[10px] text-(--color-text-subtle)">
          {agents.join(' · ')}
        </span>
      </div>

      <div
        ref={scrollRef}
        className="max-h-80 space-y-2 overflow-y-auto rounded-md bg-(--bg-key) p-2.5"
      >
        {lines.map((line) => {
          // Delegation — a system row between bubbles, like the chat's
          // inter-agent events: centered, quiet, names carry the meaning.
          if (line.kind === 'delegate') {
            return (
              <div key={line.key} className="px-1 py-0.5 text-center text-[11px] leading-4">
                <span className="text-(--color-text-subtle)">
                  <AgentName agent={line.agent} />{' '}
                  <ArrowRight size={10} className="inline text-(--color-text-subtle)" aria-hidden="true" />{' '}
                  <AgentName agent={line.to ?? '?'} />
                </span>
                {line.text && (
                  <span className="mx-auto mt-0.5 block max-w-[92%] truncate text-(--color-text-subtle)" title={line.text}>
                    {line.text}
                  </span>
                )}
              </div>
            )
          }

          // Handoff — a compact echo of the chat's HandoffCard: left bubble
          // with an accent border and a status badge.
          if (line.kind === 'handoff') {
            return (
              <div key={line.key} className="flex justify-start">
                <div className="max-w-[92%] rounded-lg rounded-bl-sm border border-(--color-accent)/30 bg-(--bg-page) px-2.5 py-1.5 shadow-sm">
                  <p className="mb-0.5 flex items-center gap-1.5 text-[10px]">
                    <CornerDownLeft size={10} className="shrink-0 text-(--color-accent)" aria-hidden="true" />
                    <span className="font-semibold tracking-wide text-(--color-text-2)">
                      Handoff from {line.agent}
                    </span>
                    {line.status && (
                      <span className="rounded bg-(--bg-key) px-1 py-px text-[10px] text-(--color-text-muted)">
                        {line.status}
                      </span>
                    )}
                    {line.at && (
                      <span className="ml-auto text-(--color-text-subtle)">{timeOf(line.at)}</span>
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

          // The pipeline prompt — right-aligned like a user message.
          if (line.kind === 'prompt') {
            return (
              <div key={line.key} className="flex justify-end">
                <div className="max-w-[92%] rounded-lg rounded-br-sm border border-(--color-border) bg-(--bg-page) px-2.5 py-1.5">
                  <p className="mb-0.5 flex items-center justify-between gap-2 text-[10px] text-(--color-text-subtle)">
                    <span className="font-semibold uppercase tracking-wider">run prompt</span>
                    {line.at && <span>{timeOf(line.at)}</span>}
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

          // Agent message — a left chat bubble: name + time header, prose
          // body (click to expand), tool calls as chips inside the bubble.
          return (
            <div key={line.key} className="flex justify-start">
              <div className="max-w-[92%] rounded-lg rounded-bl-sm border border-(--color-border) bg-(--bg-page) px-2.5 py-1.5">
                <p className="mb-0.5 flex items-center gap-2 text-[10px]">
                  <AgentName agent={line.agent} />
                  {line.at && (
                    <span className="text-(--color-text-subtle)">{timeOf(line.at)}</span>
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
                        className="flex items-center gap-1 rounded bg-(--bg-key) px-1.5 py-0.5 font-mono text-[10px] text-(--color-text-muted)"
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

        {/* Typing-style indicator — the run is live; more is coming. */}
        {active && (
          <div className="flex items-center gap-1.5 px-1 text-[11px] text-(--color-text-subtle)">
            <Loader2 size={10} className="animate-spin" aria-hidden="true" />
            {lastAgent ? (
              <>
                <AgentName agent={lastAgent} />
                <span>is working…</span>
              </>
            ) : (
              'working…'
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function NodeRunRow({ node }: { node: WorkflowNodeRun }) {
  const [open, setOpen] = useState(false)
  const hasDetail = Boolean(node.error) || Boolean(node.output && Object.keys(node.output).length)
  const duration = node.ended_at
    ? `${Math.max(0, (new Date(node.ended_at).getTime() - new Date(node.started_at).getTime()) / 1000).toFixed(1)}s`
    : null

  return (
    <div className="rounded border border-(--color-border)/60">
      <button
        type="button"
        onClick={() => hasDetail && setOpen((v) => !v)}
        className={cn(
          'flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-xs',
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
        <NodeStatusIcon status={node.status} />
        <span className="min-w-0 flex-1 truncate font-mono text-(--color-text-2)">
          {node.node_id}
          {node.iteration !== null && (
            <span className="text-(--color-text-subtle)"> #{node.iteration}</span>
          )}
        </span>
        {duration && (
          <span className="shrink-0 text-[10px] text-(--color-text-subtle)">{duration}</span>
        )}
      </button>
      {open && (
        <div className="space-y-1 border-t border-(--color-border)/60 px-2 py-1.5">
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
      <p className="whitespace-pre-wrap text-xs leading-5 text-(--color-text)">
        {item.question}
      </p>
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
}) {
  const status = displayStatus(Boolean(run.running), execution)
  const finished = !(status === 'running' || status === 'waiting_gate')
  return (
    <tr className="border-t border-(--color-border)">
      <td className="max-w-0 truncate py-2 pr-3 text-(--color-text)" title={run.title ?? run.id}>
        {run.title ?? run.id.slice(0, 8)}
      </td>
      <td className="py-2 pr-3 font-mono text-[11px] text-(--color-text-muted)">
        {execution?.definition_name ?? '—'}
      </td>
      <td className="py-2 pr-3" title={execution?.error ?? undefined}>
        <span className="flex items-center gap-2">
          <StatusBadge status={status} />
          {aimRun && <VerdictChip verdict={aimRun.verdict} />}
        </span>
      </td>
      <td
        className="py-2 pr-3 text-(--color-text-muted)"
        title={run.created_at ? new Date(run.created_at).toLocaleString() : undefined}
      >
        {formatRelativeDate(run.created_at)}
      </td>
      <td className="py-2 pr-3 text-(--color-text-muted)">
        {executionDuration(execution)}
      </td>
      <td className="py-2 text-right">
        <span className="inline-flex items-center gap-1">
          <button
            type="button"
            onClick={onMonitor}
            className={cn(
              'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] transition-colors',
              monitorOpen
                ? 'bg-(--bg-key) text-(--color-accent)'
                : status === 'waiting_gate'
                  ? 'text-(--color-warning,orange) hover:bg-(--bg-key)'
                  : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
            )}
            title="Node progress, per-node log, and the gate if one is waiting"
          >
            {status === 'waiting_gate' ? <CirclePause size={11} /> : <Activity size={11} />}
            {status === 'waiting_gate' ? 'Answer' : 'Monitor'}
          </button>
          {aimRun && (
            <button
              type="button"
              onClick={onReport}
              className={cn(
                'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] transition-colors',
                reportOpen
                  ? 'bg-(--bg-key) text-(--color-accent)'
                  : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
              )}
              title="Verdict, stats, and the full report for this run"
            >
              <FileText size={11} />
              Report
            </button>
          )}
          {finished && (
            <button
              type="button"
              onClick={onDiscuss}
              className={cn(
                'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] transition-colors',
                discussionOpen
                  ? 'bg-(--bg-key) text-(--color-accent)'
                  : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
              )}
              title="Open this run's transcript (post-run only)"
            >
              <MessageSquareText size={11} />
              Discussion
            </button>
          )}
        </span>
      </td>
    </tr>
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
      <div className="flex items-center justify-between gap-2 border-b border-(--color-border) px-3 py-2">
        <p className="min-w-0 truncate text-xs font-medium text-(--color-text)">
          Report
          <span className="ml-1.5 truncate font-normal text-(--color-text-subtle)">
            {resolvedTitle}
          </span>
        </p>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close report"
          className="shrink-0 rounded p-0.5 text-(--color-text-muted) hover:text-(--color-text)"
        >
          <X size={13} />
        </button>
      </div>

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
