/**
 * AskUserQuestionModal — floating bar (same slot as PermissionApprovalModal,
 * right above the input) showing one clarifying question at a time from the
 * batch the agent asked via the `ask_user` tool. Step through with
 * next/back; the last question shows Submit instead of Next.
 */
import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, HelpCircle, Send } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

import { replyAskUserQuestion } from '@/api/client'
import { useTeamStore } from '@/stores/useTeamStore'
import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'

export function AskUserQuestionModal() {
  const askUserQuestion = useTeamStore((s) => s.askUserQuestion)
  const sessionId = useTeamStore((s) => s.sessionId)
  const preset = useMotionPreset()
  const [answers, setAnswers] = useState<string[]>([])
  const [step, setStep] = useState(0)
  const [replying, setReplying] = useState(false)
  const [replyError, setReplyError] = useState<string | null>(null)

  useEffect(() => {
    setAnswers(askUserQuestion ? askUserQuestion.questions.map(() => '') : [])
    setStep(0)
    setReplyError(null)
  }, [askUserQuestion])

  if (!askUserQuestion || !sessionId) return null

  const { questions } = askUserQuestion
  const q = questions[step]
  const isLast = step === questions.length - 1
  const currentAnswered = (answers[step] ?? '').trim().length > 0
  const allAnswered = answers.length > 0 && answers.every((a) => a.trim().length > 0)

  const setAnswer = (value: string) => {
    setAnswers((prev) => prev.map((a, i) => (i === step ? value : a)))
  }

  const handleSend = async () => {
    setReplying(true)
    setReplyError(null)
    try {
      await replyAskUserQuestion(sessionId, askUserQuestion.requestId, answers.map((a) => a.trim()))
      useTeamStore.setState({ askUserQuestion: null })
    } catch (err) {
      setReplyError(err instanceof Error ? err.message : 'Failed to send reply. Please try again.')
    } finally {
      setReplying(false)
    }
  }

  return (
    <AnimatePresence>
      <motion.div
        key={askUserQuestion.requestId}
        initial={{ opacity: 0, y: 6 * preset.distance }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 6 * preset.distance }}
        className="mx-auto w-full max-w-3xl px-4 pb-2"
      >
        <div className="rounded-xl border border-(--color-primary)/30 bg-(--bg-page) shadow-sm overflow-hidden">
          {/* Top bar */}
          <div className="flex items-center gap-2 border-b border-(--color-border) bg-(--color-primary)/5 px-4 py-2.5">
            <HelpCircle size={14} className="shrink-0 text-(--color-primary)" aria-hidden="true" />
            <span className="text-xs font-semibold text-(--color-text)">Agent has a question</span>
            {questions.length > 1 && (
              <span className="text-xs text-(--color-text-muted)">— {step + 1}/{questions.length}</span>
            )}
          </div>

          {/* Question */}
          <AnimatePresence mode="wait">
            <motion.div
              key={step}
              initial={{ opacity: 0, x: 8 * preset.distance }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -8 * preset.distance }}
              className="space-y-2 px-4 py-3"
            >
              <p className="text-sm text-(--color-text)">{q.question}</p>
              {q.options.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {q.options.map((option, oi) => (
                    <button
                      key={oi}
                      type="button"
                      disabled={replying}
                      onClick={() => setAnswer(option)}
                      className={cn(
                        'rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
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
                  else setStep((s) => s + 1)
                }}
                disabled={replying}
                placeholder={q.options.length > 0 ? 'Or type your own answer…' : 'Type your answer…'}
                className="h-8 w-full rounded-md border border-(--color-border) bg-(--bg-card) px-2.5 text-xs text-(--color-text) outline-none focus:border-(--color-primary)"
                autoFocus
              />
            </motion.div>
          </AnimatePresence>

          {/* Actions */}
          <div className="flex items-center justify-between gap-3 border-t border-(--color-border) px-4 py-2.5">
            <button
              type="button"
              disabled={replying || step === 0}
              onClick={() => setStep((s) => s - 1)}
              className={cn(
                'flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs font-medium text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)',
                (replying || step === 0) && 'pointer-events-none opacity-40',
              )}
            >
              <ChevronLeft size={13} aria-hidden="true" />
              Back
            </button>

            {replyError && <p className="text-xs text-red-600 dark:text-red-400">{replyError}</p>}

            {isLast ? (
              <button
                type="button"
                disabled={replying || !allAnswered}
                onClick={handleSend}
                className={cn(
                  'flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors',
                  'bg-(--color-primary) text-white hover:opacity-90',
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
                onClick={() => setStep((s) => s + 1)}
                className={cn(
                  'flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors',
                  'bg-(--color-primary) text-white hover:opacity-90',
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
    </AnimatePresence>
  )
}
