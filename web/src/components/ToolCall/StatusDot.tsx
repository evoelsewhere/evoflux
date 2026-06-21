/**
 * Status dot — matches the ``AgentCapabilities`` colour vocabulary so a
 * tool call's running state reads consistently with agent-level status.
 */

import type { ToolCallState } from './types'

export function StatusDot({ state }: { state: ToolCallState }) {
  const cls =
    state === 'start'
      ? 'bg-(--color-text-muted)'
      : state === 'running'
        ? 'animate-pulse bg-(--color-marker-orange) shadow-[0_0_5px_var(--color-marker-orange)]'
        : state === 'failed'
          ? 'bg-(--color-error)'
          : 'bg-(--color-success)'
  return (
    <span
      className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${cls}`}
      aria-hidden
    />
  )
}
