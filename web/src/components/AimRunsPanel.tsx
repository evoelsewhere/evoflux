/**
 * AimRunsPanel — Runs & Reports: the project-wide compare/run history
 * (aim_runs) with the report viewer (aim-mode-shell-ux-spec.md v2.2 §5.3).
 * Deep-linkable: /aim/$projectId/runs/$runId preselects a run, and picking
 * one keeps the URL in sync. Each run can open its workflow's node log
 * (Run Monitor) and — when it has a session — the post-run Discussion.
 * TeamChatView is a singleton, exactly one instance mounted at a time.
 */

import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  CircleAlert,
  CircleCheck,
  CircleX,
  Loader2,
  MessageSquareText,
  X,
} from 'lucide-react'
import { getAimRun, listAimRuns } from '@/api/client'
import { queryKeys } from '@/queries/keys'
import { cn } from '@/lib/utils'
import { resolveAimRolePath } from '@/components/AimKbPanel'
import { AimSidePanel } from '@/components/AimSidePanel'
import { RunMonitorPanel } from '@/components/AimPipelinesPanel'
import { TeamChatView } from '@/components/TeamChatView'
import type { CodingProject } from '@/api/types'

function VerdictIcon({ verdict, size = 12 }: { verdict: string; size?: number }) {
  switch (verdict) {
    case 'pass':
      return <CircleCheck size={size} className="shrink-0 text-(--color-success)" />
    case 'acceptable_diff':
      return <CircleCheck size={size} className="shrink-0 text-(--color-warning,orange)" />
    case 'error':
      return <CircleAlert size={size} className="shrink-0 text-(--color-error)" />
    default:
      return <CircleX size={size} className="shrink-0 text-(--color-error)" />
  }
}

function verdictBadgeTone(verdict: string | undefined): string {
  switch (verdict) {
    case 'pass':
      return 'bg-(--color-success-bg,var(--bg-key)) text-(--color-success,inherit)'
    case 'acceptable_diff':
      return 'bg-(--bg-key) text-(--color-warning,orange)'
    default:
      return 'bg-(--color-error-subtle,var(--bg-key)) text-(--color-error)'
  }
}

export function AimRunsPanel({ project, runId }: { project: CodingProject; runId?: string }) {
  const navigate = useNavigate()
  // URL is the source of truth when deep-linked; local state covers plain
  // /aim/$projectId/runs (no run picked yet → null).
  const [localRunId, setLocalRunId] = useState<string | null>(null)
  const selectedRunId = runId ?? localRunId
  // Side-panel targets are built from the run DETAIL, not the list — a
  // deep-linked run older than the list page must still open both panels.
  const [discussion, setDiscussion] = useState<{
    runId: string
    sessionId: string
    title: string
  } | null>(null)
  const [monitorRun, setMonitorRun] = useState<{
    runId: string
    sessionId: string
    executionId: string | null
    title: string
  } | null>(null)

  const targetWorkspace = resolveAimRolePath(project, 'target')

  const selectRun = (id: string) => {
    setLocalRunId(id)
    // §3.2 — keep the run's URL shareable.
    navigate({
      to: '/aim/$projectId/runs/$runId',
      params: { projectId: project.id, runId: id },
      replace: true,
    })
  }

  const runsQuery = useQuery({
    queryKey: [...queryKeys.projects.detail(project.id), 'aim-runs-list'],
    queryFn: () => listAimRuns(project.id),
    refetchInterval: 10_000,
  })
  const runs = runsQuery.data ?? []

  const detailQuery = useQuery({
    queryKey: queryKeys.projects.aimRun(project.id, selectedRunId ?? ''),
    queryFn: () => getAimRun(project.id, selectedRunId as string),
    enabled: Boolean(selectedRunId),
  })

  // Display name for the side panels — the list row when we have it, else
  // the detail's kind (deep-linked runs can be older than the list page).
  const panelTitle = (): string => {
    const listRun = runs.find((r) => r.id === selectedRunId)
    if (listRun) return `${listRun.unit} · ${listRun.kind}`
    const detail = detailQuery.data
    return detail ? `${detail.kind} · ${String(selectedRunId).slice(0, 8)}` : ''
  }

  return (
    <div className="flex h-full min-h-0">
      <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col">
        <div className="border-b border-(--color-border) px-4 py-3">
          <p className="text-sm font-medium text-(--color-text)">Runs & Reports</p>
        </div>

        <div className="flex min-h-0 flex-1">
          {/* Run history */}
          <div className="w-80 shrink-0 overflow-y-auto border-r border-(--color-border) p-2">
            {runsQuery.isLoading ? (
              <p className="px-2 py-1 text-xs text-(--color-text-subtle)">Loading runs…</p>
            ) : runs.length === 0 ? (
              <p className="px-2 py-1 text-xs text-(--color-text-subtle)">
                No compare runs recorded yet.
              </p>
            ) : (
              runs.map((run) => (
                <button
                  key={run.id}
                  type="button"
                  onClick={() => selectRun(run.id)}
                  className={cn(
                    'flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors',
                    selectedRunId === run.id
                      ? 'bg-(--bg-key) text-(--color-text)'
                      : 'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)',
                  )}
                >
                  <VerdictIcon verdict={run.verdict} />
                  <span className="min-w-0 flex-1 truncate">
                    {run.unit}
                    <span className="text-(--color-text-subtle)"> · {run.kind}</span>
                    {run.case_set && (
                      <span className="text-(--color-text-subtle)"> · {run.case_set}</span>
                    )}
                  </span>
                  <span className="shrink-0 text-[10px] text-(--color-text-subtle)">
                    {new Date(run.created_at).toLocaleTimeString()}
                  </span>
                </button>
              ))
            )}
          </div>

          {/* Report viewer */}
          <div className="min-w-0 flex-1 overflow-y-auto p-4">
            {!selectedRunId ? (
              <p className="text-xs text-(--color-text-subtle)">Select a run to view its report.</p>
            ) : detailQuery.isLoading ? (
              <p className="flex items-center gap-1.5 text-xs text-(--color-text-subtle)">
                <Loader2 size={12} className="animate-spin" /> Loading report…
              </p>
            ) : detailQuery.isError ? (
              <p className="text-xs text-(--color-error)">Failed to load the run.</p>
            ) : (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm">
                  <span
                    className={cn(
                      'rounded px-2 py-0.5 text-xs font-medium',
                      verdictBadgeTone(detailQuery.data?.verdict),
                    )}
                  >
                    {detailQuery.data?.verdict}
                  </span>
                  <span className="text-xs text-(--color-text-muted)">
                    {detailQuery.data?.kind}
                    {detailQuery.data?.case_set ? ` · ${detailQuery.data.case_set}` : ''}
                  </span>
                  <span className="ml-auto flex items-center gap-1">
                    {/* Node-level log of the workflow that produced this run */}
                    {(detailQuery.data?.workflow_execution_id ||
                      detailQuery.data?.session_id) && (
                      <button
                        type="button"
                        onClick={() => {
                          const detail = detailQuery.data
                          if (!detail || !selectedRunId) return
                          setDiscussion(null)
                          setMonitorRun(
                            monitorRun?.runId === selectedRunId
                              ? null
                              : {
                                  runId: selectedRunId,
                                  sessionId: detail.session_id ?? '',
                                  executionId: detail.workflow_execution_id,
                                  title: panelTitle(),
                                },
                          )
                        }}
                        className={cn(
                          'flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium transition-colors',
                          monitorRun?.runId === selectedRunId
                            ? 'bg-(--bg-key) text-(--color-accent)'
                            : 'text-(--color-text-muted) hover:text-(--color-text)',
                        )}
                        title="This run's workflow nodes and per-node log"
                      >
                        <Activity size={12} />
                        Nodes
                      </button>
                    )}
                    {/* §5.3 — Discussion button only when run has a session */}
                    {detailQuery.data?.session_id && (
                      <button
                        type="button"
                        onClick={() => {
                          const detail = detailQuery.data
                          if (!detail?.session_id || !selectedRunId) return
                          setMonitorRun(null)
                          setDiscussion(
                            discussion?.runId === selectedRunId
                              ? null
                              : {
                                  runId: selectedRunId,
                                  sessionId: detail.session_id,
                                  title: panelTitle(),
                                },
                          )
                        }}
                        className={cn(
                          'flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium transition-colors',
                          discussion?.runId === selectedRunId
                            ? 'bg-(--bg-key) text-(--color-accent)'
                            : 'text-(--color-text-muted) hover:text-(--color-text)',
                        )}
                      >
                        <MessageSquareText size={12} />
                        Discussion
                      </button>
                    )}
                  </span>
                </div>
                {Object.keys(detailQuery.data?.stats ?? {}).length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(detailQuery.data?.stats ?? {}).map(([key, value]) => (
                      <div key={key} className="rounded bg-(--bg-key) px-2.5 py-1.5">
                        <p className="text-[10px] text-(--color-text-subtle)">{key}</p>
                        <p className="text-xs font-medium text-(--color-text)">{String(value)}</p>
                      </div>
                    ))}
                  </div>
                )}
                {detailQuery.data?.report ? (
                  <pre className="overflow-x-auto rounded bg-(--bg-key) p-3 font-mono text-[11px] leading-4 text-(--color-text-2)">
                    {JSON.stringify(detailQuery.data.report, null, 2)}
                  </pre>
                ) : (
                  <p className="text-xs text-(--color-text-subtle)">
                    No report file on this machine
                    {detailQuery.data?.report_path ? ` (${detailQuery.data.report_path})` : ''}.
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Workflow node log for the selected (finished) run. */}
      {monitorRun && (monitorRun.sessionId || monitorRun.executionId) && !discussion && (
        <RunMonitorPanel
          sessionId={monitorRun.sessionId}
          title={monitorRun.title}
          sessionRunning={false}
          executionId={monitorRun.executionId}
          onClose={() => setMonitorRun(null)}
        />
      )}

      {/* Post-run Discussion — singleton TeamChatView, only when run has a session.
          Shares the same constraint as AimPipelinesPanel: exactly one instance mounted. */}
      {discussion && !monitorRun && (
        <AimSidePanel storageKey="oa.aimDiscussion.width" defaultWidth={420}>
          <div className="flex items-center justify-between gap-2 border-b border-(--color-border) px-3 py-2">
            <p className="min-w-0 truncate text-xs font-medium text-(--color-text)">
              Discussion
              <span className="ml-1.5 font-normal text-(--color-text-subtle)">
                {discussion.title}
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
              sessionId={discussion.sessionId}
              mode="aim"
              workspace={targetWorkspace}
            />
          </div>
        </AimSidePanel>
      )}
    </div>
  )
}
