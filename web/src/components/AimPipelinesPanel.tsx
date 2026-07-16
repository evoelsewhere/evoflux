/**
 * AimPipelinesPanel — trigger pipelines with plain UI and watch run status
 * (aim-mode-shell-ux-spec.md v2.2 §3.3/§5.2). NO chat: the Run button
 * resolves a fresh per-run session (mode="aim", project-scoped) and posts
 * the pipeline instruction into it under the hood — the same execution
 * substrate the composer/scheduler use, never a second path. Run status is
 * a polled table; the post-run Discussion entry point lives in
 * Runs & Reports (FE-3), not here.
 *
 * Pre-Workflows the "pipeline" is a well-formed instruction to the aim
 * roster; AIM-4 swaps the send for POST /api/workflows/{name}/run without
 * touching this surface's shape.
 */

import { useCallback, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CircleCheck, CircleX, Loader2, Play, TriangleAlert } from 'lucide-react'
import { listAimUnits, listTeamSessions, postTeamChat, resolveTeamSession } from '@/api/client'
import { queryKeys } from '@/queries/keys'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { CodingProject, SessionResponse } from '@/api/types'

interface PipelineDef {
  key: string
  label: string
  needsUnit: boolean
  /** Writes into the target repo → extra confirmation before running. */
  mutatesTarget: boolean
  instruction: (unit: string | null) => string
}

const PIPELINES: PipelineDef[] = [
  {
    key: 'assess',
    label: 'Assess (inventory + waves)',
    needsUnit: false,
    mutatesTarget: false,
    instruction: () =>
      'Run the ASSESS pipeline for this AIM project: index the source estate, ' +
      'build the unit inventory into the KB repo (modules/<module>/<unit>.md stubs ' +
      'with frontmatter phase=inventory plus inventory/units.md), score complexity, ' +
      'and propose waves. Record every unit via the aim_units tool.',
  },
  {
    key: 'understand-unit',
    label: 'Understand unit',
    needsUnit: true,
    mutatesTarget: false,
    instruction: (unit) =>
      `Run the UNDERSTAND-UNIT pipeline for unit ${unit}: follow the ` +
      'aim-legacy-comprehension skill (bottom-up — document dependencies first if ' +
      'their docs are missing), write the unit doc into the KB, extract candidate ' +
      'business rules, then set the unit phase to understood via aim_units.',
  },
  {
    key: 'convert-unit',
    label: 'Convert unit',
    needsUnit: true,
    mutatesTarget: true,
    instruction: (unit) =>
      `Run the CONVERT-UNIT pipeline for unit ${unit}: implement it in the target ` +
      'repo following the KB mapping and target-conventions, respecting the rulebook ' +
      'mappings. The base source is read-only. Set the unit phase to converted via ' +
      'aim_units when the target builds.',
  },
  {
    key: 'compare-unit',
    label: 'Compare unit',
    needsUnit: true,
    mutatesTarget: false,
    instruction: (unit) =>
      `Run the COMPARE-UNIT pipeline for unit ${unit}: execute the legacy and target ` +
      'runners for its golden cases, canonicalize both outputs, then diff them with the ' +
      'aim_compare tool (which records the AimRun). If equivalent, set the phase to ' +
      'equivalent; if not, summarize the diff for triage.',
  },
]

export function AimPipelinesPanel({ project }: { project: CodingProject }) {
  const queryClient = useQueryClient()
  const [pipelineKey, setPipelineKey] = useState(PIPELINES[0].key)
  const [unitInput, setUnitInput] = useState('')
  const [confirmArmed, setConfirmArmed] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const pipeline = PIPELINES.find((p) => p.key === pipelineKey) ?? PIPELINES[0]

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

  const canRun = !starting && (!pipeline.needsUnit || unitInput.trim().length > 0)

  const handleRun = useCallback(async () => {
    if (pipeline.mutatesTarget && !confirmArmed) {
      // Writing into the target repo gets a second, explicit click.
      setConfirmArmed(true)
      setTimeout(() => setConfirmArmed(false), 4000)
      return
    }
    setConfirmArmed(false)
    setStarting(true)
    setError(null)
    try {
      const unit = pipeline.needsUnit ? unitInput.trim() : null
      // A fresh per-run session — never reuse: parallel unit runs, and each
      // transcript stays a self-contained audit artifact (spec §3.3).
      const session = await resolveTeamSession({
        mode: 'aim',
        project_id: project.id,
        create: true,
      })
      await postTeamChat(
        pipeline.instruction(unit),
        session.id,
        false,
        undefined,
        'aim',
        session.workspace ?? null,
      )
      void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessions.project(project.id) })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start the pipeline run.')
    } finally {
      setStarting(false)
    }
  }, [pipeline, unitInput, confirmArmed, project.id, queryClient])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-(--color-border) px-4 py-3">
        <p className="text-sm font-medium text-(--color-text)">Pipelines</p>
      </div>

      {/* Trigger form */}
      <div className="flex flex-wrap items-end gap-2 border-b border-(--color-border) p-4">
        <label className="flex flex-col gap-1 text-xs text-(--color-text-muted)">
          Pipeline
          <select
            value={pipelineKey}
            onChange={(e) => {
              setPipelineKey(e.target.value)
              setConfirmArmed(false)
            }}
            className="rounded-md border border-(--color-border) bg-(--bg-subtle) px-2 py-1.5 text-xs text-(--color-text)"
          >
            {PIPELINES.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        {pipeline.needsUnit && (
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
        <Button
          size="sm"
          variant={confirmArmed ? 'destructive' : 'default'}
          onClick={() => void handleRun()}
          disabled={!canRun}
        >
          {starting ? (
            <Loader2 size={12} className="animate-spin" />
          ) : confirmArmed ? (
            <TriangleAlert size={12} />
          ) : (
            <Play size={12} />
          )}
          {confirmArmed ? 'Confirm — writes to target' : 'Run'}
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
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <RunRow key={run.id} run={run} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

function RunRow({ run }: { run: SessionResponse }) {
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
          ) : run.title?.toLowerCase().includes('fail') ? (
            <>
              <CircleX size={11} className="text-(--color-error)" /> done
            </>
          ) : (
            <>
              <CircleCheck size={11} className="text-(--color-success)" /> done
            </>
          )}
        </span>
      </td>
      <td className="py-2 text-(--color-text-muted)">
        {run.created_at ? new Date(run.created_at).toLocaleString() : '—'}
      </td>
    </tr>
  )
}
