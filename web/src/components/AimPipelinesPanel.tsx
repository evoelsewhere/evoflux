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
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CirclePause,
  CircleX,
  Loader2,
  MessageSquareText,
  OctagonX,
  Play,
  ShieldCheck,
  X,
} from 'lucide-react'
import {
  approveWorkflow,
  getExecution,
  getPendingQuestions,
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
import { resolveAimRolePath } from '@/components/AimKbPanel'
import { Button } from '@/components/ui/button'
import { TeamChatView } from '@/components/TeamChatView'
import { cn } from '@/lib/utils'
import type {
  CodingProject,
  MessageResponse,
  SessionResponse,
  WorkflowExecutionSummary,
  WorkflowNodeRun,
} from '@/api/types'

interface PipelineDef {
  key: string
  workflow: string
  label: string
  needs: 'none' | 'unit' | 'wave'
  hasCaseSet?: boolean
}

const PIPELINES: PipelineDef[] = [
  { key: 'assess', workflow: 'aim-assess', label: 'Assess (inventory + waves)', needs: 'none' },
  { key: 'understand', workflow: 'aim-understand', label: 'Understand unit', needs: 'unit' },
  { key: 'convert-unit', workflow: 'aim-convert-unit', label: 'Convert unit', needs: 'unit' },
  { key: 'convert-wave', workflow: 'aim-convert-wave', label: 'Convert wave', needs: 'wave' },
  { key: 'compare', workflow: 'aim-test-compare', label: 'Test-compare unit', needs: 'unit', hasCaseSet: true },
  { key: 'cutover', workflow: 'aim-cutover-check', label: 'Cutover check (wave)', needs: 'wave' },
]

// §9.3: pipelines that write to the target repo — require confirm before run.
const CONVERT_KEYS = new Set(['convert-unit', 'convert-wave'])

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

function displayStatus(
  sessionRunning: boolean,
  execution: WorkflowExecutionSummary | undefined,
): RunDisplayStatus {
  if (!execution) return sessionRunning ? 'running' : 'done'
  if (execution.status === 'running' || execution.status === 'waiting_gate') {
    // The sessions list and the executions list poll independently (5s) — a
    // just-started run can briefly show a live execution before its session
    // reads running=true. Only call it interrupted once it's old enough
    // that the polls must have converged.
    const ageMs = Date.now() - new Date(execution.started_at).getTime()
    if (!sessionRunning && ageMs > 20_000) return 'interrupted'
    return execution.status as RunDisplayStatus
  }
  return execution.status as RunDisplayStatus
}

export function AimPipelinesPanel({ project }: { project: CodingProject }) {
  const queryClient = useQueryClient()
  const targetWorkspace = resolveAimRolePath(project, 'target')
  const [pipelineKey, setPipelineKey] = useState(PIPELINES[0].key)
  const [unitInput, setUnitInput] = useState('')
  const [waveInput, setWaveInput] = useState('0')
  const [caseSet, setCaseSet] = useState<'smoke' | 'full'>('smoke')
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // §9.3: convert pipelines write to the target repo — confirm before run.
  const [confirmOpen, setConfirmOpen] = useState(false)
  // The one chat surface in the whole mode: a finished run's transcript.
  const [discussion, setDiscussion] = useState<SessionResponse | null>(null)
  // Run Monitor: node progress + log + inline gate for one run's session.
  const [monitorSession, setMonitorSession] = useState<SessionResponse | null>(null)

  const pipeline = PIPELINES.find((p) => p.key === pipelineKey) ?? PIPELINES[0]

  const workflowsQ = useWorkflowsQuery(targetWorkspace)
  const workflowByName = useMemo(
    () => new Map((workflowsQ.data?.workflows ?? []).map((wf) => [wf.name, wf])),
    [workflowsQ.data],
  )
  const selectedWorkflow = workflowByName.get(pipeline.workflow)

  const unitsQuery = useQuery({
    queryKey: queryKeys.projects.aimUnits(project.id, undefined),
    queryFn: () => listAimUnits(project.id),
    staleTime: 30_000,
  })
  const unitOptions = useMemo(
    () => (unitsQuery.data ?? []).map((u) => `${u.module}/${u.name}`).sort(),
    [unitsQuery.data],
  )

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
  })
  const executionBySession = useMemo(() => {
    // Newest-first from the API — keep the latest execution per session.
    const map = new Map<string, WorkflowExecutionSummary>()
    for (const ex of executionsQuery.data?.executions ?? []) {
      if (!map.has(ex.session_id)) map.set(ex.session_id, ex)
    }
    return map
  }, [executionsQuery.data])

  const canRun =
    !starting &&
    Boolean(selectedWorkflow?.valid) &&
    (pipeline.needs !== 'unit' || unitInput.trim().length > 0) &&
    (pipeline.needs !== 'wave' || waveInput.trim().length > 0)

  const buildInputs = useCallback((): Record<string, unknown> => {
    if (pipeline.needs === 'unit') {
      const inputs: Record<string, unknown> = { unit: unitInput.trim() }
      if (pipeline.hasCaseSet) inputs.case_set = caseSet
      return inputs
    }
    if (pipeline.needs === 'wave') return { wave: Number(waveInput) }
    return {}
  }, [pipeline, unitInput, caseSet, waveInput])

  // Spec §3.3 — per-run sessions are named `<unit|wave>/<pipeline>` so the
  // run table and Discussion header read like the wireframe, not like UUIDs.
  const runLabel = useCallback((): string => {
    if (pipeline.needs === 'unit') return `${unitInput.trim()} · ${pipeline.key}`
    if (pipeline.needs === 'wave') return `wave ${waveInput.trim()} · ${pipeline.key}`
    return pipeline.key
  }, [pipeline, unitInput, waveInput])

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
      setMonitorSession({ ...session, title, running: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start the pipeline run.')
    } finally {
      setStarting(false)
    }
  }, [selectedWorkflow, targetWorkspace, project.id, buildInputs, runLabel, queryClient])

  // §9.3: convert pipelines write to the target repo — require explicit confirm.
  const handleRun = useCallback(() => {
    if (CONVERT_KEYS.has(pipelineKey)) {
      setConfirmOpen(true)
    } else {
      void doRun()
    }
  }, [pipelineKey, doRun])

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
            <select
              value={pipelineKey}
              onChange={(e) => setPipelineKey(e.target.value)}
              className="rounded-md border border-(--color-border) bg-(--bg-subtle) px-2 py-1.5 text-xs text-(--color-text)"
            >
              {PIPELINES.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          {pipeline.needs === 'unit' && (
            <label className="flex min-w-48 flex-col gap-1 text-xs text-(--color-text-muted)">
              Unit
              {unitOptions.length > 0 ? (
                <select
                  value={unitInput}
                  onChange={(e) => setUnitInput(e.target.value)}
                  className="rounded-md border border-(--color-border) bg-(--bg-subtle) px-2 py-1.5 text-xs text-(--color-text)"
                >
                  <option value="">Select a unit…</option>
                  {unitOptions.map((unit) => (
                    <option key={unit} value={unit}>
                      {unit}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={unitInput}
                  onChange={(e) => setUnitInput(e.target.value)}
                  placeholder="module/UNIT (run assess first)"
                  className="rounded-md border border-(--color-border) bg-(--bg-subtle) px-2 py-1.5 text-xs text-(--color-text) placeholder:text-(--color-text-muted)"
                />
              )}
            </label>
          )}
          {pipeline.needs === 'wave' && (
            <label className="flex w-24 flex-col gap-1 text-xs text-(--color-text-muted)">
              Wave
              <input
                type="number"
                value={waveInput}
                onChange={(e) => setWaveInput(e.target.value)}
                className="rounded-md border border-(--color-border) bg-(--bg-subtle) px-2 py-1.5 text-xs text-(--color-text)"
              />
            </label>
          )}
          {pipeline.hasCaseSet && (
            <label className="flex flex-col gap-1 text-xs text-(--color-text-muted)">
              Case set
              <select
                value={caseSet}
                onChange={(e) => setCaseSet(e.target.value as 'smoke' | 'full')}
                className="rounded-md border border-(--color-border) bg-(--bg-subtle) px-2 py-1.5 text-xs text-(--color-text)"
              >
                <option value="smoke">smoke</option>
                <option value="full">full</option>
              </select>
            </label>
          )}
          <Button size="sm" onClick={() => handleRun()} disabled={!canRun || starting}>
            {starting ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
            Run
          </Button>
          {error && <p className="basis-full text-[11px] text-(--color-error)">{error}</p>}
        </div>

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
                  <th className="pb-2" />
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <RunRow
                    key={run.id}
                    run={run}
                    execution={executionBySession.get(run.id)}
                    monitorOpen={monitorSession?.id === run.id}
                    discussionOpen={discussion?.id === run.id}
                    onMonitor={() => {
                      setDiscussion(null)
                      setMonitorSession((prev) => (prev?.id === run.id ? null : run))
                    }}
                    onDiscuss={() => {
                      setMonitorSession(null)
                      setDiscussion((prev) => (prev?.id === run.id ? null : run))
                    }}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Run Monitor — node progress + per-node log + inline gate. Not chat. */}
      {monitorSession && !discussion && (() => {
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
              setDiscussion(liveRun)
            }}
          />
        )
      })()}

      {/* Post-run Discussion — TeamChatView is a global singleton; exactly one
          instance, mounted only while a finished run's transcript is open. */}
      {discussion && !monitorSession && (
        <div className="flex w-96 shrink-0 flex-col border-l border-(--color-border)">
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
        </div>
      )}

      {/* §9.3 — Confirm dialog for convert pipelines (write to target repo) */}
      {confirmOpen && (
        <div
          className="absolute inset-0 z-50 flex items-center justify-center bg-black/40"
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
                  <strong>{pipeline.label}</strong> will write converted output to the target
                  source directory. This cannot be undone automatically.
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
  // session's newest execution ourselves until one shows up.
  const lookupQ = useQuery({
    queryKey: ['aim-monitor-execution', sessionId],
    queryFn: () => listWorkflowExecutions([sessionId]),
    enabled: !knownExecutionId && sessionId.length > 0,
    refetchInterval: 2_500,
  })
  const executionId = knownExecutionId ?? lookupQ.data?.executions[0]?.id

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
    <div className="flex w-96 shrink-0 flex-col border-l border-(--color-border)">
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
          <p className="flex items-center gap-1.5 text-xs text-(--color-text-subtle)">
            <Loader2 size={12} className="animate-spin" />
            Waiting for the execution to register…
          </p>
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
    </div>
  )
}

/** One line per transcript event, newest at the bottom — the run's "log".
 * Read-only on purpose: chat stays post-run only (Discussion). */
function ActivityLogSection({ sessionId, active }: { sessionId: string; active: boolean }) {
  const historyQ = useQuery({
    queryKey: ['aim-monitor-history', sessionId],
    queryFn: () => teamHistory(sessionId),
    refetchInterval: active ? 4_000 : false,
  })
  const scrollRef = useRef<HTMLDivElement>(null)

  const lines = useMemo(() => {
    const data = historyQ.data
    if (!data) return []
    const tagged: Array<{ agent: string; msg: MessageResponse }> = [
      ...data.lead.messages.map((msg) => ({ agent: 'lead', msg })),
      ...data.members.flatMap((member) =>
        member.messages.map((msg) => ({ agent: member.name, msg })),
      ),
    ]
    return tagged
      .filter(({ msg }) => !msg.is_summary && !msg.is_hidden)
      .map(({ agent, msg }) => {
        const toolNames = (msg.tool_calls ?? [])
          .map((call) => call.function?.name)
          .filter((name): name is string => Boolean(name))
        const text = (msg.content ?? '').replace(/\s+/g, ' ').trim()
        if (!text && toolNames.length === 0) return null
        if (msg.role === 'tool') return null
        return {
          key: msg.id,
          at: msg.created_at ?? '',
          agent,
          role: msg.role,
          tools: toolNames,
          text: text.length > 200 ? `${text.slice(0, 200)}…` : text,
        }
      })
      .filter((line): line is NonNullable<typeof line> => line !== null)
      .sort((a, b) => a.at.localeCompare(b.at))
      .slice(-40)
  }, [historyQ.data])

  // Keep the newest line in view as the log grows.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines.length])

  if (historyQ.isLoading || lines.length === 0) return null

  return (
    <div>
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">
        Activity log
      </p>
      <div
        ref={scrollRef}
        className="max-h-64 space-y-1 overflow-y-auto rounded-md bg-(--bg-key) p-2"
      >
        {lines.map((line) => (
          <div key={line.key} className="text-[11px] leading-4">
            <span
              className={cn(
                'font-mono',
                line.role === 'user' ? 'text-(--color-text-subtle)' : 'text-(--color-accent)',
              )}
            >
              {line.role === 'user' ? '»' : line.agent}
            </span>{' '}
            {line.text && <span className="text-(--color-text-2)">{line.text}</span>}
            {line.tools.length > 0 && (
              <span className="text-(--color-text-subtle)"> ⚙ {line.tools.join(', ')}</span>
            )}
          </div>
        ))}
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
    try {
      await replyAskUserQuestion(sessionId, batch.request_id, [value])
      void queryClient.invalidateQueries({ queryKey: ['aim-pending-questions', sessionId] })
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

function RunRow({
  run,
  execution,
  monitorOpen,
  discussionOpen,
  onMonitor,
  onDiscuss,
}: {
  run: SessionResponse
  execution?: WorkflowExecutionSummary
  monitorOpen: boolean
  discussionOpen: boolean
  onMonitor: () => void
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
        <StatusBadge status={status} />
      </td>
      <td className="py-2 pr-3 text-(--color-text-muted)">
        {run.created_at ? new Date(run.created_at).toLocaleString() : '—'}
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
