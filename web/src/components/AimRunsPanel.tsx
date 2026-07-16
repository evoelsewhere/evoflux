/**
 * AimRunsPanel — Runs & Reports: the project-wide compare/run history
 * (aim_runs) with the report viewer (aim-mode-shell-ux-spec.md v2.2 §5.3).
 * Pure data — the post-run Discussion entry lives on the finished session
 * rows in Pipelines, where the transcripts are.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CircleCheck, CircleX, Loader2 } from 'lucide-react'
import { getAimRun, listAimRuns } from '@/api/client'
import { queryKeys } from '@/queries/keys'
import { cn } from '@/lib/utils'
import type { CodingProject } from '@/api/types'

export function AimRunsPanel({ project }: { project: CodingProject }) {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)

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

  return (
    <div className="flex h-full min-h-0 flex-col">
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
                onClick={() => setSelectedRunId(run.id)}
                className={cn(
                  'flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors',
                  selectedRunId === run.id
                    ? 'bg-(--bg-key) text-(--color-text)'
                    : 'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)',
                )}
              >
                {run.verdict === 'pass' ? (
                  <CircleCheck size={12} className="shrink-0 text-(--color-success)" />
                ) : (
                  <CircleX size={12} className="shrink-0 text-(--color-error)" />
                )}
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
                    detailQuery.data?.verdict === 'pass'
                      ? 'bg-(--color-success-bg,var(--bg-key)) text-(--color-success,inherit)'
                      : 'bg-(--color-error-subtle,var(--bg-key)) text-(--color-error)',
                  )}
                >
                  {detailQuery.data?.verdict}
                </span>
                <span className="text-xs text-(--color-text-muted)">
                  {detailQuery.data?.kind}
                  {detailQuery.data?.case_set ? ` · ${detailQuery.data.case_set}` : ''}
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
  )
}
