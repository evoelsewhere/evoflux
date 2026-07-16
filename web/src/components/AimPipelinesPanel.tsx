/**
 * AimPipelinesPanel — trigger the AIM workflow library with plain UI and
 * watch run status (aim-mode-shell-ux-spec.md v2.2 §3.3/§5.2 + AIM-4).
 *
 * Since AIM-4 the Run button executes the REAL workflow definitions
 * (POST /api/workflows/{name}/run against a fresh per-run session) — same
 * execution substrate as the composer's /workflow, no second path. Gates
 * inside a pipeline surface here as a "waiting for you" row action that
 * opens the question inline (polled from the pending-questions endpoint),
 * so the whole loop — trigger, gate, result — never needs a chat surface.
 * Post-run Discussion stays the mode's only chat entry point.
 */

import { useCallback, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  CircleCheck,
  CirclePause,
  Loader2,
  MessageSquareText,
  Play,
  ShieldCheck,
  X,
} from 'lucide-react'
import {
  approveWorkflow,
  getPendingQuestions,
  listAimUnits,
  listTeamSessions,
  replyAskUserQuestion,
  resolveTeamSession,
  runWorkflow,
} from '@/api/client'
import { queryKeys } from '@/queries/keys'
import { useWorkflowsQuery } from '@/queries/useWorkflowsQuery'
import { resolveAimRolePath } from '@/components/AimKbPanel'
import { Button } from '@/components/ui/button'
import { TeamChatView } from '@/components/TeamChatView'
import { cn } from '@/lib/utils'
import type { CodingProject, SessionResponse } from '@/api/types'

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
  // A running run whose gate the user opened.
  const [gateSession, setGateSession] = useState<string | null>(null)

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
  const runs = sessionsQuery.data?.data ?? []

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
      await runWorkflow(
        selectedWorkflow.name,
        session.id,
        buildInputs(),
        targetWorkspace,
      )
      void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessions.project(project.id) })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start the pipeline run.')
    } finally {
      setStarting(false)
    }
  }, [selectedWorkflow, targetWorkspace, project.id, buildInputs, queryClient])

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
                    isOpen={discussion?.id === run.id}
                    onDiscuss={() => setDiscussion(run)}
                    onOpenGate={() => setGateSession(run.id)}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Gate banner — answer a workflow gate without any chat surface. */}
      {gateSession && (
        <GatePanel sessionId={gateSession} onClose={() => setGateSession(null)} />
      )}

      {/* Post-run Discussion — TeamChatView is a global singleton; exactly one
          instance, mounted only while a finished run's transcript is open. */}
      {discussion && !gateSession && (
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

function GatePanel({ sessionId, onClose }: { sessionId: string; onClose: () => void }) {
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
      onClose()
    } finally {
      setReplying(false)
    }
  }

  return (
    <div className="flex w-96 shrink-0 flex-col border-l border-(--color-border)">
      <div className="flex items-center justify-between gap-2 border-b border-(--color-border) px-3 py-2">
        <p className="text-xs font-medium text-(--color-text)">Gate</p>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close gate"
          className="shrink-0 rounded p-0.5 text-(--color-text-muted) hover:text-(--color-text)"
        >
          <X size={13} />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {pendingQ.isLoading ? (
          <p className="text-xs text-(--color-text-subtle)">Checking for a pending gate…</p>
        ) : !item ? (
          <p className="text-xs text-(--color-text-subtle)">
            No gate is waiting on this run right now.
          </p>
        ) : (
          <>
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
          </>
        )}
      </div>
    </div>
  )
}

function RunRow({
  run,
  isOpen,
  onDiscuss,
  onOpenGate,
}: {
  run: SessionResponse
  isOpen: boolean
  onDiscuss: () => void
  onOpenGate: () => void
}) {
  return (
    <tr className="border-t border-(--color-border)">
      <td className="max-w-0 truncate py-2 pr-3 text-(--color-text)" title={run.title ?? run.id}>
        {run.title ?? run.id.slice(0, 8)}
      </td>
      <td className="py-2 pr-3">
        <span
          className={cn(
            'inline-flex items-center gap-1',
            run.running ? 'text-(--color-accent)' : 'text-(--color-text-muted)',
          )}
        >
          {run.running ? (
            <>
              <Loader2 size={11} className="animate-spin" /> running
            </>
          ) : (
            <>
              <CircleCheck size={11} className="text-(--color-success)" /> done
            </>
          )}
        </span>
      </td>
      <td className="py-2 pr-3 text-(--color-text-muted)">
        {run.created_at ? new Date(run.created_at).toLocaleString() : '—'}
      </td>
      <td className="py-2 text-right">
        {run.running ? (
          <button
            type="button"
            onClick={onOpenGate}
            className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            title="Answer this run's gate, if one is waiting"
          >
            <CirclePauseIcon />
            Gate
          </button>
        ) : (
          <button
            type="button"
            onClick={onDiscuss}
            className={cn(
              'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] transition-colors',
              isOpen
                ? 'bg-(--bg-key) text-(--color-accent)'
                : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
            )}
            title="Open this run's transcript (post-run only)"
          >
            <MessageSquareText size={11} />
            Discussion
          </button>
        )}
      </td>
    </tr>
  )
}

function CirclePauseIcon() {
  return <CirclePause size={11} />
}
