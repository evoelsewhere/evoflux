/**
 * AskUserQuestionModal — floating bar (same slot as PermissionApprovalModal,
 * right above the input) showing one clarifying question at a time from the
 * batch the agent asked via the `ask_user` tool. Step through with
 * next/back; the last question shows Submit instead of Next.
 */
import { forwardRef, useState } from 'react'
import { ChevronLeft, ChevronRight, HelpCircle, Send } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

import { replyAskUserQuestion } from '@/api/client'
import { useTeamStore } from '@/stores/useTeamStore'
import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'
import type { AskUserQuestionPending } from '@/api/types'

/** Survives connectStream gate-clear + reconnect remount of the same request. */
const askUserDrafts = new Map<string, { answers: string[]; step: number }>()

function readDraft(requestId: string, questionCount: number) {
  const draft = askUserDrafts.get(requestId)
  if (!draft || draft.answers.length !== questionCount) {
    return { answers: Array.from({ length: questionCount }, () => ''), step: 0 }
  }
  return {
    answers: draft.answers,
    step: Math.min(Math.max(draft.step, 0), Math.max(questionCount - 1, 0)),
  }
}

function writeDraft(requestId: string, answers: string[], step: number) {
  askUserDrafts.set(requestId, { answers, step })
}

function clearDraft(requestId: string) {
  askUserDrafts.delete(requestId)
}

const AskUserQuestionForm = forwardRef<
  HTMLDivElement,
  {
    askUserQuestion: AskUserQuestionPending
    sessionId: string
  }
>(function AskUserQuestionForm({ askUserQuestion, sessionId }, ref) {
  const preset = useMotionPreset()
  const { questions } = askUserQuestion
  const initial = readDraft(askUserQuestion.requestId, questions.length)
  const [answers, setAnswers] = useState(() => initial.answers)
  const [step, setStep] = useState(() => initial.step)
  const [replying, setReplying] = useState(false)
  const [replyError, setReplyError] = useState<string | null>(null)

  const q = questions[step]
  if (!q) return null

  const isLast = step === questions.length - 1
  const currentAnswered = (answers[step] ?? '').trim().length > 0
  const allAnswered = answers.length > 0 && answers.every((a) => a.trim().length > 0)

  const setAnswer = (value: string) => {
    setAnswers((prev) => {
      const next = prev.map((a, i) => (i === step ? value : a))
      writeDraft(askUserQuestion.requestId, next, step)
      return next
    })
  }

  const goToStep = (nextStep: number) => {
    setStep(nextStep)
    writeDraft(askUserQuestion.requestId, answers, nextStep)
  }

  const handleSend = async () => {
    setReplying(true)
    setReplyError(null)
    try {
      // Prefer the event session_id (matches AimOverviewPanel) so replies
      // hit the service that owns the pending batch, not a switched lead id.
      const replySessionId = askUserQuestion.sessionId || sessionId
      await replyAskUserQuestion(
        replySessionId,
        askUserQuestion.requestId,
        answers.map((a) => a.trim()),
      )
      clearDraft(askUserQuestion.requestId)
      useTeamStore.setState({ askUserQuestion: null })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to send reply. Please try again.'
      // Already resolved (other tab / interrupt while we were away) — dismiss.
      if (/not found|already resolved/i.test(message)) {
        clearDraft(askUserQuestion.requestId)
        useTeamStore.setState({ askUserQuestion: null })
        return
      }
      setReplyError(message)
    } finally {
      setReplying(false)
    }
  }

  return (
    <motion.div
      ref={ref}
      role="region"
      aria-label="Agent questions"
      initial={{ opacity: 0, y: 6 * preset.distance }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 6 * preset.distance }}
      transition={preset.spring}
      className="mx-auto w-full max-w-3xl px-4 pb-2"
    >
      <div className="overflow-hidden rounded-xl border border-(--color-primary)/35 bg-(--bg-page) shadow-sm">
        <div className="flex items-center gap-2 border-b border-(--color-border) bg-(--color-primary)/5 px-4 py-2.5">
          <HelpCircle size={14} className="shrink-0 text-(--color-primary)" aria-hidden="true" />
          <span className="text-xs font-semibold text-(--color-text)">Agent has a question</span>
          {questions.length > 1 && (
            <span className="text-xs text-(--color-text-muted)">— {step + 1}/{questions.length}</span>
          )}
        </div>

        <AnimatePresence mode="wait">
          <motion.div
            key={step}
            initial={{ opacity: 0, x: 8 * preset.distance }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -8 * preset.distance }}
            transition={preset.spring}
            className="space-y-2 px-4 py-3"
          >
            <p className="text-sm text-(--color-text)">{q.question}</p>
            {q.options.length > 0 && (
              <div className="flex flex-wrap gap-1.5" role="group" aria-label="Suggested answers">
                {q.options.map((option, oi) => (
                  <button
                    key={oi}
                    type="button"
                    disabled={replying}
                    onClick={() => setAnswer(option)}
                    aria-pressed={answers[step] === option}
                    className={cn(
                      'rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)',
                      answers[step] === option
                        ? 'border-(--color-primary) bg-(--color-primary) text-white'
                        : 'border-(--color-border) bg-(--bg-card) text-(--color-text) hover:bg-(--bg-key)',
                      replying && 'pointer-events-none opacity-50',
                    )}
                  >
                    {option}
                  </button>
                ))}
              </div>
            )}
            <input
              type="text"
              value={answers[step] ?? ''}
              onChange={(e) => setAnswer(e.target.value)}
              onKeyDown={(e) => {
                if (e.key !== 'Enter' || !currentAnswered) return
                if (isLast) void handleSend()
                else goToStep(step + 1)
              }}
              disabled={replying}
              placeholder={q.options.length > 0 ? 'Or type your own answer…' : 'Type your answer…'}
              aria-label={q.question}
              className="h-8 w-full rounded-md border border-(--color-border) bg-(--bg-card) px-2.5 text-xs text-(--color-text) outline-none focus:border-(--color-primary)"
              autoFocus
            />
          </motion.div>
        </AnimatePresence>

        <div className="flex items-center justify-between gap-3 border-t border-(--color-border) px-4 py-2.5">
          <button
            type="button"
            disabled={replying || step === 0}
            onClick={() => goToStep(step - 1)}
            className={cn(
              'flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs font-medium text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)',
              (replying || step === 0) && 'pointer-events-none opacity-40',
            )}
          >
            <ChevronLeft size={13} aria-hidden="true" />
            Back
          </button>

          {replyError && (
            <p className="text-xs text-red-600 dark:text-red-400" role="alert">{replyError}</p>
          )}

          {isLast ? (
            <button
              type="button"
              disabled={replying || !allAnswered}
              onClick={handleSend}
              className={cn(
                'flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors',
                'bg-(--color-primary) text-white hover:opacity-90',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)',
                (replying || !allAnswered) && 'pointer-events-none opacity-50',
              )}
            >
              <Send size={12} aria-hidden="true" />
              {replying ? 'Sending…' : 'Submit'}
            </button>
          ) : (
            <button
              type="button"
              disabled={!currentAnswered}
              onClick={() => goToStep(step + 1)}
              className={cn(
                'flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors',
                'bg-(--color-primary) text-white hover:opacity-90',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)',
                !currentAnswered && 'pointer-events-none opacity-50',
              )}
            >
              Next
              <ChevronRight size={12} aria-hidden="true" />
            </button>
          )}
        </div>
      </div>
    </motion.div>
  )
})

export function AskUserQuestionModal() {
  const askUserQuestion = useTeamStore((s) => s.askUserQuestion)
  const sessionId = useTeamStore((s) => s.sessionId)
  const visible = Boolean(askUserQuestion && sessionId && askUserQuestion.questions[0])

  return (
    <AnimatePresence>
      {visible && askUserQuestion && sessionId ? (
        <AskUserQuestionForm
          key={askUserQuestion.requestId}
          askUserQuestion={askUserQuestion}
          sessionId={sessionId}
        />
      ) : null}
    </AnimatePresence>
  )
}
