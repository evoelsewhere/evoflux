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
  getExecution,
  getPendingQuestions,
  getWorkflow,
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
import { MarkdownBlock } from '@/utils/markdown'
import { formatRelativeDate } from '@/utils/format'
import { takeAimPipelinePrefill } from '@/lib/aimHandoff'
import { cn } from '@/lib/utils'
import type {
  AimUnitOut,
  CodingProject,
  MessageResponse,
  SessionResponse,
  WorkflowExecutionSummary,
  WorkflowListItem,
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

export function AimPipelinesPanel({ project }: { project: CodingProject }) {
  const queryClient = useQueryClient()
  const targetWorkspace = resolveAimRolePath(project, 'target')
  // A unit card's quick action lands here with the form pre-filled —
  // consumed once, then this screen behaves as if hand-opened.
  const [prefill] = useState(() => takeAimPipelinePrefill())
  const [pipelineKey, setPipelineKey] = useState(() =>
    prefill && PIPELINES.some((p) => p.key === prefill.pipeline)
      ? prefill.pipeline
      : PIPELINES[0].key,
  )
  const [unitInput, setUnitInput] = useState(prefill?.unit ?? '')
  const [waveInput, setWaveInput] = useState(
    prefill?.wave != null ? String(prefill.wave) : '0',
  )
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
    queryKey: ['workflow-detail', pipeline.workflow, targetWorkspace ?? ''],
    queryFn: () => getWorkflow(pipeline.workflow, targetWorkspace),
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
                    <option key={unit.key} value={unit.key}>
                      {unit.key} · {unit.phase}
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

        {/* What this pipeline does — description, node chain, readiness. */}
        <PipelineInfoCard
          workflow={selectedWorkflow}
          graph={detailQ.data?.graph}
          pipelineKey={pipeline.key}
          units={units}
          wave={pipeline.needs === 'wave' ? Number(waveInput) : null}
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
 * before hitting Run, not after a confusing no-op. */
function eligibility(
  pipelineKey: string,
  units: AimUnitOut[],
  wave: number | null,
): { text: string; warn: boolean } | null {
  const count = (phase: string, w?: number | null) =>
    units.filter((u) => u.phase === phase && (w == null || u.wave === w)).length
  switch (pipelineKey) {
    case 'assess':
      return {
        text:
          units.length === 0
            ? 'Builds the unit inventory from the source estate — the KB has no units yet.'
            : `Refreshes the inventory — ${units.length} unit(s) currently indexed.`,
        warn: false,
      }
    case 'understand': {
      const n = count('inventory')
      return {
        text: `${n} unit(s) at phase inventory await documentation.`,
        warn: n === 0 && units.length > 0,
      }
    }
    case 'convert-unit': {
      const n = count('designed')
      return {
        text: `${n} unit(s) at phase designed (plan → gate → implement; the plan step designs first if needed).`,
        warn: false,
      }
    }
    case 'convert-wave': {
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
    case 'compare': {
      const n = count('converted')
      return {
        text: `${n} unit(s) at phase converted awaiting an equivalence verdict.`,
        warn: false,
      }
    }
    case 'cutover': {
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
  pipelineKey,
  units,
  wave,
}: {
  workflow: WorkflowListItem | undefined
  graph: Record<string, unknown> | undefined
  pipelineKey: string
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
  const hint = eligibility(pipelineKey, units, wave)

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
  const executionId = knownExecutionId ?? lookupQ.data?.executions[0]?.id
  const lookupExhausted =
    !knownExecutionId && !executionId && lookupQ.dataUpdateCount >= 12

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
    </div>
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
