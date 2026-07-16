/**
 * WorkflowProgressPill — the LoopStatusPill clone for workflow executions
 * (plan v5 §9.1): "<name>: <node> (i/n)", red on failure, ✕ stops the
 * execution (covers gates/inline nodes where the Stop button has no turn
 * to interrupt).
 */

import { Loader2, OctagonX, X } from 'lucide-react'
import { stopExecution } from '@/api/client'
import { cn } from '@/lib/utils'
import type { ActiveWorkflowExecution } from '@/stores/useTeamStore/types'

export function WorkflowProgressPill({
  execution,
  onDismissFailed,
}: {
  execution: ActiveWorkflowExecution
  onDismissFailed: () => void
}) {
  const failed = execution.status === 'failed'
  const progress =
    execution.nodeIndex !== null
      ? `${execution.nodeIndex}/${execution.totalNodes}`
      : `${execution.totalNodes} nodes`
  const label = execution.nodeId
    ? `${execution.definitionName}: ${execution.nodeId} (${progress})`
    : `${execution.definitionName} (${progress})`

  return (
    <span
      className={cn(
        'inline-flex max-w-72 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs',
        failed
          ? 'border-(--color-error)/40 bg-(--color-error-subtle,var(--bg-key)) text-(--color-error)'
          : 'border-(--color-border) bg-(--bg-key) text-(--color-text-2)',
      )}
      title={failed ? (execution.error ?? 'failed') : label}
    >
      {failed ? (
        <OctagonX size={12} className="shrink-0" />
      ) : execution.status === 'waiting_gate' ? (
        <span className="size-2 shrink-0 animate-pulse rounded-full bg-(--color-accent)" />
      ) : (
        <Loader2 size={12} className="shrink-0 animate-spin" />
      )}
      <span className="truncate">
        {failed ? `${execution.definitionName} failed` : label}
        {execution.status === 'waiting_gate' && ' · waiting for you'}
      </span>
      <button
        type="button"
        aria-label={failed ? 'Dismiss' : 'Stop workflow'}
        onClick={() => {
          if (failed) onDismissFailed()
          else void stopExecution(execution.executionId).catch(() => {})
        }}
        className="shrink-0 rounded-full p-0.5 hover:bg-(--bg-page)"
      >
        <X size={11} />
      </button>
    </span>
  )
}
