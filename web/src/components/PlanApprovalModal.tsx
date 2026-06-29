/**
 * PlanApprovalModal — displays the agent's plan steps and lets the user
 * approve or reject them before any destructive operations are executed.
 */
import { useState } from 'react'
import { CheckCircle2, ClipboardList, XCircle } from 'lucide-react'

import { replyPlanApproval } from '@/api/client'
import { useTeamStore } from '@/stores/useTeamStore'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { PlanStep } from '@/api/types'

const TOOL_ICON_MAP: Record<string, string> = {
  edit: '✏️',
  write: '📝',
  patch: '🩹',
  rm: '🗑️',
  shell: '💻',
  python: '🐍',
  bg: '⚙️',
}

function StepRow({ step, index }: { step: PlanStep; index: number }) {
  const icon = TOOL_ICON_MAP[step.tool] ?? '🔧'
  return (
    <div className="flex items-start gap-3 rounded-lg border border-(--color-border) bg-(--bg-card) p-3">
      <span className="mt-0.5 shrink-0 text-base leading-none" aria-hidden="true">
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="rounded bg-(--bg-key) px-1.5 py-0.5 font-mono text-xs text-(--color-text-muted)">
            {step.tool}
          </span>
          <span className="text-xs font-semibold text-(--color-text-muted)">
            Step {index + 1}
          </span>
        </div>
        <p className="mt-1 break-all text-sm text-(--color-text)">{step.summary}</p>
      </div>
    </div>
  )
}

export function PlanApprovalModal() {
  const planApproval = useTeamStore((s) => s.planApproval)
  const sessionId = useTeamStore((s) => s.sessionId)
  const [replying, setReplying] = useState(false)
  const [replyError, setReplyError] = useState<string | null>(null)

  if (!planApproval || !sessionId) return null

  const { requestId, steps } = planApproval

  const handleReply = async (decision: 'approved' | 'rejected') => {
    setReplying(true)
    setReplyError(null)
    try {
      await replyPlanApproval(sessionId, requestId, decision)
      useTeamStore.setState({ planApproval: null })
    } catch (err) {
      setReplyError(err instanceof Error ? err.message : 'Failed to send reply. Please try again.')
    } finally {
      setReplying(false)
    }
  }

  return (
    <div
      className="pointer-events-auto fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="plan-approval-title"
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" aria-hidden="true" />

      {/* Panel */}
      <div className="relative z-10 w-full max-w-lg overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-page) shadow-2xl">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-(--color-border) px-5 py-4">
          <ClipboardList size={18} className="shrink-0 text-(--color-primary)" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <h2 id="plan-approval-title" className="text-sm font-semibold text-(--color-text)">
              Review plan before execution
            </h2>
            <p className="text-xs text-(--color-text-muted)">
              {steps.length} step{steps.length !== 1 ? 's' : ''} — no changes have been made yet
            </p>
          </div>
        </div>

        {/* Steps */}
        <div className="max-h-72 space-y-2 overflow-y-auto px-5 py-4">
          {steps.map((step, i) => (
            <StepRow key={i} step={step} index={i} />
          ))}
        </div>

        {/* Actions */}
        <div className="flex flex-col gap-2 border-t border-(--color-border) px-5 py-4">
          {replyError && (
            <p className="text-xs text-red-600 dark:text-red-400">{replyError}</p>
          )}
          <div className="flex items-center justify-end gap-2">
            <Button
              variant="ghost"
              size="sm"
              disabled={replying}
              onClick={() => handleReply('rejected')}
              className={cn(
                'gap-1.5 text-red-600 hover:bg-red-500/10 hover:text-red-600 dark:text-red-400',
                replying && 'opacity-50',
              )}
            >
              <XCircle size={14} aria-hidden="true" />
              Reject plan
            </Button>
            <Button
              variant="default"
              size="sm"
              disabled={replying}
              onClick={() => handleReply('approved')}
              className="gap-1.5"
            >
              <CheckCircle2 size={14} aria-hidden="true" />
              {replying ? 'Approving…' : 'Approve & execute'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
