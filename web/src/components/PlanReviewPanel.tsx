/**
 * PlanReviewPanel — Claude-Code-style plan review.
 *
 * While a plan-approval request is pending, the agent's markdown plan is
 * rendered in a resizable panel beside the chat. Selecting text in the
 * plan pops an inline comment box; submitting it quotes the selection
 * into the chat composer so the user can accumulate revision notes and
 * send them as one revise reply. `PlanActionBar` (mounted above the
 * composer) carries the Accept / Revise / Reject actions.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  CheckCircle2,
  ClipboardList,
  ListChecks,
  MessageSquarePlus,
  PencilLine,
  XCircle,
} from 'lucide-react'

import { replyPlanApproval } from '@/api/client'
import { useTeamStore } from '@/stores/useTeamStore'
import { useToastStore } from '@/stores/useToastStore'
import { useIsMobile } from '@/hooks/use-mobile'
import { useReducedMotion } from '@/hooks/useReducedMotion'
import { useResizableWidth } from '@/hooks/use-resizable-width'
import { LazyMarkdownBlock } from '@/utils/LazyMarkdownBlock'
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
    <div className="flex items-start gap-2.5 rounded-lg border border-(--color-border) bg-(--bg-card) p-2.5">
      <span className="mt-0.5 shrink-0 text-sm leading-none" aria-hidden="true">
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="rounded-xs bg-(--bg-key) px-1.5 py-0.5 font-mono text-xs text-(--color-text-muted)">
            {step.tool}
          </span>
          <span className="text-xs font-semibold text-(--color-text-muted)">Step {index + 1}</span>
        </div>
        <p className="mt-1 break-all text-xs text-(--color-text)">{step.summary}</p>
      </div>
    </div>
  )
}

interface SelectionState {
  text: string
  /** Viewport coordinates of the selection rect (popover anchor). */
  top: number
  left: number
}

/**
 * Inline comment box anchored under the current text selection. Submitting
 * quotes the selection + comment into the chat composer via onQuoteComment.
 */
function SelectionCommentPopover({
  selection,
  onSubmit,
  onDismiss,
}: {
  selection: SelectionState
  onSubmit: (comment: string) => void
  onDismiss: () => void
}) {
  const [comment, setComment] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    textareaRef.current?.focus()
  }, [])

  // Clamp within the viewport so the popover never overflows off-screen.
  const width = 320
  const left = Math.min(Math.max(selection.left, 8), window.innerWidth - width - 8)
  const top = Math.min(selection.top, window.innerHeight - 140)

  return (
    <div
      className="fixed z-50 rounded-xl border border-(--color-border) bg-(--bg-page) p-2 shadow-xl"
      style={{ top, left, width }}
      role="dialog"
      aria-label="Comment on selected plan text"
      onMouseDown={(e) => e.stopPropagation()}
    >
      <p className="mb-1.5 line-clamp-2 rounded bg-(--bg-key) px-2 py-1 text-xs italic text-(--color-text-muted)">
        “{selection.text.length > 160 ? `${selection.text.slice(0, 160)}…` : selection.text}”
      </p>
      <textarea
        ref={textareaRef}
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onDismiss()
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            if (comment.trim()) onSubmit(comment.trim())
          }
        }}
        rows={2}
        placeholder="Suggest a change to this part…"
        className="w-full resize-none rounded-lg border border-(--color-border) bg-(--bg-card) px-2 py-1.5 text-xs text-(--color-text) outline-none placeholder:text-(--color-text-subtle) focus:border-(--color-primary)"
      />
      <div className="mt-1.5 flex items-center justify-end gap-1.5">
        <button
          type="button"
          onClick={onDismiss}
          className="rounded-lg px-2 py-1 text-xs text-(--color-text-muted) hover:bg-(--bg-key)"
        >
          Cancel
        </button>
        <button
          type="button"
          disabled={!comment.trim()}
          onClick={() => comment.trim() && onSubmit(comment.trim())}
          className={cn(
            'flex items-center gap-1 rounded-lg bg-(--color-primary) px-2 py-1 text-xs font-medium text-white hover:opacity-90',
            !comment.trim() && 'pointer-events-none opacity-50',
          )}
        >
          <MessageSquarePlus size={12} aria-hidden="true" />
          Add to chat
        </button>
      </div>
    </div>
  )
}

export function PlanReviewPanel({
  onQuoteComment,
}: {
  /** Quote the selected plan text + comment into the chat composer. */
  onQuoteComment: (quote: string, comment: string) => void
}) {
  const planApproval = useTeamStore((s) => s.planApproval)
  const isMobile = useIsMobile()
  const prefersReducedMotion = useReducedMotion()
  const resizable = useResizableWidth({
    storageKey: 'planPanelWidth',
    defaultWidth: 380,
    minWidth: 300,
    maxWidth: 640,
    edge: 'right',
    disabled: isMobile,
  })
  const bodyRef = useRef<HTMLDivElement | null>(null)
  const [selection, setSelection] = useState<SelectionState | null>(null)
  const [stepsOpen, setStepsOpen] = useState(false)

  const captureSelection = useCallback(() => {
    const sel = window.getSelection()
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) {
      setSelection(null)
      return
    }
    const container = bodyRef.current
    if (!container || !container.contains(sel.anchorNode) || !container.contains(sel.focusNode)) {
      return
    }
    const text = sel.toString().trim()
    if (!text) {
      setSelection(null)
      return
    }
    const rect = sel.getRangeAt(0).getBoundingClientRect()
    setSelection({ text, top: rect.bottom + 6, left: rect.left })
  }, [])

  const dismissPopover = useCallback(() => {
    setSelection(null)
    window.getSelection()?.removeAllRanges()
  }, [])

  const submitComment = useCallback(
    (comment: string) => {
      if (selection) onQuoteComment(selection.text, comment)
      dismissPopover()
    },
    [dismissPopover, onQuoteComment, selection],
  )

  // Reset transient UI whenever a new (or no) plan request is active.
  useEffect(() => {
    setSelection(null)
    setStepsOpen(false)
  }, [planApproval?.requestId])

  return (
    <AnimatePresence>
      {planApproval && (
        <motion.aside
          key={planApproval.requestId}
          initial={prefersReducedMotion || isMobile ? { opacity: 0 } : { width: 0 }}
          animate={prefersReducedMotion || isMobile ? { opacity: 1 } : { width: resizable.width }}
          exit={prefersReducedMotion || isMobile ? { opacity: 0 } : { width: 0 }}
          transition={{ duration: prefersReducedMotion ? 0.01 : 0.22, ease: [0.4, 0, 0.2, 1] }}
          className={cn(
            'fixed bottom-0 left-0 z-40 min-h-0 w-full overflow-hidden border-r border-(--color-border) bg-(--bg-card) shadow-xl md:relative md:inset-y-auto md:left-auto md:z-auto md:w-auto md:shrink-0 md:shadow-none',
            isMobile ? 'mobile-safe-top max-w-none' : '',
          )}
          aria-label="Plan review"
        >
          <div className="relative flex h-full min-h-0 w-full flex-col">
            {!isMobile && (
              <div
                role="separator"
                aria-orientation="vertical"
                aria-label="Resize plan panel"
                title="Drag to resize · double-click to reset"
                className="absolute right-0 top-0 z-20 h-full w-1 cursor-col-resize transition-colors hover:bg-(--color-accent)/40"
                onPointerDown={resizable.startResize}
                onDoubleClick={resizable.resetWidth}
              />
            )}

            <header className="flex shrink-0 items-center gap-2.5 border-b border-(--color-border) px-3 py-3">
              <ClipboardList size={16} className="shrink-0 text-(--color-primary)" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-(--color-text-subtle)">
                  Plan review
                </p>
                <p className="mt-0.5 text-xs text-(--color-text-muted)">
                  No changes made yet — select text to comment
                </p>
              </div>
            </header>

            <div
              ref={bodyRef}
              onMouseUp={captureSelection}
              onKeyUp={captureSelection}
              className="min-h-0 flex-1 select-text overflow-y-auto px-4 py-3"
            >
              {planApproval.plan.trim() ? (
                <div className="oa-prose text-sm">
                  <LazyMarkdownBlock content={planApproval.plan} />
                </div>
              ) : (
                <p className="text-xs italic text-(--color-text-subtle)">
                  The agent did not include a plan document — review the recorded steps below.
                </p>
              )}

              {planApproval.steps.length > 0 && (
                <div className="mt-4 border-t border-(--color-border) pt-3">
                  <button
                    type="button"
                    onClick={() => setStepsOpen((v) => !v)}
                    className="flex w-full items-center gap-2 text-left text-xs font-semibold text-(--color-text-muted) hover:text-(--color-text)"
                    aria-expanded={stepsOpen}
                  >
                    <ListChecks size={13} aria-hidden="true" />
                    Steps to execute ({planApproval.steps.length})
                    <span className="ml-auto text-(--color-text-subtle)">{stepsOpen ? '−' : '+'}</span>
                  </button>
                  {stepsOpen && (
                    <div className="mt-2 space-y-1.5">
                      {planApproval.steps.map((step, i) => (
                        <StepRow key={i} step={step} index={i} />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {selection && (
            <SelectionCommentPopover
              selection={selection}
              onSubmit={submitComment}
              onDismiss={dismissPopover}
            />
          )}
        </motion.aside>
      )}
    </AnimatePresence>
  )
}

/**
 * Floating action strip above the composer while a plan is pending:
 * Accept & execute / Revise (focus the composer) / Reject. Typing a
 * message and sending it while the plan is pending is intercepted by
 * TeamChatView and delivered as a `revise` reply with that feedback.
 */
export function PlanActionBar({ onRevise }: { onRevise: () => void }) {
  const planApproval = useTeamStore((s) => s.planApproval)
  const sessionId = useTeamStore((s) => s.sessionId)
  const [replying, setReplying] = useState(false)
  const [replyError, setReplyError] = useState<string | null>(null)

  const handleReply = async (decision: 'approved' | 'rejected') => {
    if (!planApproval || !sessionId) return
    setReplying(true)
    setReplyError(null)
    try {
      await replyPlanApproval(sessionId, planApproval.requestId, decision)
      useTeamStore.setState({ planApproval: null })
      if (decision === 'approved') {
        useToastStore.getState().push({ tone: 'success', title: 'Plan approved — executing' })
      }
    } catch (err) {
      setReplyError(err instanceof Error ? err.message : 'Failed to send reply. Please try again.')
    } finally {
      setReplying(false)
    }
  }

  return (
    <AnimatePresence>
      {planApproval && (
        <motion.div
          key={planApproval.requestId}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 6 }}
          transition={{ duration: 0.15 }}
          className="mx-auto w-full max-w-3xl px-4 pb-2"
        >
          <div className="overflow-hidden rounded-xl border border-(--color-primary)/30 bg-(--bg-page) shadow-sm">
            <div className="flex flex-wrap items-center gap-3 px-4 py-2.5">
              <div className="flex min-w-0 flex-1 items-center gap-2">
                <ClipboardList size={14} className="shrink-0 text-(--color-primary)" aria-hidden="true" />
                <span className="text-xs font-semibold text-(--color-text)">Plan ready for review</span>
                <span className="hidden text-xs text-(--color-text-muted) sm:inline">
                  — type a message to request changes
                </span>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <button
                  disabled={replying}
                  onClick={() => handleReply('rejected')}
                  className={cn(
                    'flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors',
                    'text-red-600 hover:bg-red-500/10 dark:text-red-400',
                    replying && 'pointer-events-none opacity-50',
                  )}
                >
                  <XCircle size={12} aria-hidden="true" />
                  Reject
                </button>
                <button
                  disabled={replying}
                  onClick={onRevise}
                  className={cn(
                    'flex items-center gap-1 rounded-lg border border-(--color-border) px-2.5 py-1.5 text-xs font-medium transition-colors',
                    'bg-(--bg-card) text-(--color-text) hover:bg-(--bg-key)',
                    replying && 'pointer-events-none opacity-50',
                  )}
                >
                  <PencilLine size={12} aria-hidden="true" />
                  Revise
                </button>
                <button
                  disabled={replying}
                  onClick={() => handleReply('approved')}
                  className={cn(
                    'flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors',
                    'bg-(--color-primary) text-white hover:opacity-90',
                    replying && 'pointer-events-none opacity-50',
                  )}
                >
                  <CheckCircle2 size={12} aria-hidden="true" />
                  {replying ? 'Sending…' : 'Accept & execute'}
                </button>
              </div>
            </div>
            {replyError && (
              <p className="border-t border-(--color-border) px-4 py-2 text-xs text-red-600 dark:text-red-400">
                {replyError}
              </p>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
