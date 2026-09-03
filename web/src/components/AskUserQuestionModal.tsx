/**
 * AskUserQuestionModal — floating bar (same slot as PermissionApprovalModal,
 * right above the input) showing one clarifying question at a time from the
 * batch the agent asked via the `ask_user` tool. Step through with
 * next/back; the last question shows Submit instead of Next.
 */
import { forwardRef, useState } from 'react'
import { Bot, ChevronDown, ChevronLeft, ChevronRight, HelpCircle, Send, X } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

import { replyAskUserQuestion } from '@/api/client'
import { useTeamStore } from '@/stores/useTeamStore'
import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'
import type { AskUserQuestionPending } from '@/api/types'
import { useRegistryQuery } from '@/queries'
import { ModelOptions } from '@/components/model-picker/ModelOptions'
import {
  buildThinkingOptions,
  normalizeModelId,
  reconcileThinkingLevel,
  shortModelName,
  thinkingColor,
} from '@/lib/model-settings'

/** Survives connectStream gate-clear + reconnect remount of the same request. */
const askUserDrafts = new Map<string, { answers: string[]; step: number }>()

function defaultAnswers(questions: AskUserQuestionPending['questions']): string[] {
  return questions.map((question) => {
    if (question.kind !== 'agent_spawn' || !question.agentSpawn) return ''
    return JSON.stringify({
      model: question.agentSpawn.defaultModel,
      thinking_level: question.agentSpawn.defaultThinkingLevel,
    })
  })
}

function readDraft(requestId: string, questions: AskUserQuestionPending['questions']) {
  const draft = askUserDrafts.get(requestId)
  if (!draft || draft.answers.length !== questions.length) {
    return { answers: defaultAnswers(questions), step: 0 }
  }
  return {
    answers: draft.answers,
    step: Math.min(Math.max(draft.step, 0), Math.max(questions.length - 1, 0)),
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
  const registry = useRegistryQuery()
  const { questions } = askUserQuestion
  const initial = readDraft(askUserQuestion.requestId, questions)
  const [answers, setAnswers] = useState(() => initial.answers)
  const [step, setStep] = useState(() => initial.step)
  const [replying, setReplying] = useState(false)
  const [replyError, setReplyError] = useState<string | null>(null)
  const [modelPickerOpen, setModelPickerOpen] = useState(false)

  const q = questions[step]
  if (!q) return null

  // Defend against a duplicated choice reaching the UI: two identical buttons
  // are one answer, selecting either lights both, and a two-way question whose
  // branches read the same leaves the second reachable only by free text.
  const options = q.options.filter(
    (option, index, all) =>
      option.trim().length > 0 &&
      all.findIndex((other) => other.trim().toLowerCase() === option.trim().toLowerCase()) === index,
  )

  const spawnSpec = q.kind === 'agent_spawn' ? q.agentSpawn ?? null : null
  const isAgentSpawn = spawnSpec !== null
  const allowsFreeText = !q.strict
  const spawnSelection = (() => {
    if (spawnSpec === null) return null
    try {
      const parsed = JSON.parse(answers[step] ?? '') as Record<string, unknown>
      return {
        model: typeof parsed.model === 'string' ? parsed.model : spawnSpec.defaultModel,
        thinkingLevel: typeof parsed.thinking_level === 'string' ? parsed.thinking_level : null,
      }
    } catch {
      return {
        model: spawnSpec.defaultModel,
        thinkingLevel: spawnSpec.defaultThinkingLevel,
      }
    }
  })()
  const selectedModel = registry.data?.models.find((model) => model.id === spawnSelection?.model)
  const thinkingOptions = buildThinkingOptions(selectedModel?.thinking_levels ?? [])

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

  const setSpawnSelection = (model: string, thinkingLevel: string | null) => {
    setAnswer(JSON.stringify({ model, thinking_level: thinkingLevel }))
  }

  const goToStep = (nextStep: number) => {
    setStep(nextStep)
    writeDraft(askUserQuestion.requestId, answers, nextStep)
  }

  const handleSend = async (answerOverride?: string[]) => {
    setReplying(true)
    setReplyError(null)
    try {
      // Prefer the event session_id so replies
      // hit the service that owns the pending batch, not a switched lead id.
      const replySessionId = askUserQuestion.sessionId || sessionId
      await replyAskUserQuestion(
        replySessionId,
        askUserQuestion.requestId,
        (answerOverride ?? answers).map((a) => a.trim()),
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
      className={cn(
        'mx-auto w-full px-4 pb-2',
        isAgentSpawn ? 'max-w-2xl' : 'max-w-3xl',
      )}
    >
      <div className="overflow-hidden rounded-xl border border-(--color-primary)/35 bg-(--bg-page) shadow-sm">
        <div className={cn(
          'flex items-center gap-2 border-b border-(--color-border) bg-(--color-primary)/5',
          isAgentSpawn ? 'px-3 py-2' : 'px-4 py-2.5',
        )}>
          {isAgentSpawn ? (
            <Bot size={14} className="shrink-0 text-(--color-primary)" aria-hidden="true" />
          ) : (
            <HelpCircle size={14} className="shrink-0 text-(--color-primary)" aria-hidden="true" />
          )}
          <span className="text-xs font-semibold text-(--color-text)">
            {spawnSpec ? `Spawn ${spawnSpec.blueprint}` : 'Agent has a question'}
          </span>
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
            className={cn(
              'space-y-2',
              isAgentSpawn ? 'px-3 py-2.5' : 'px-4 py-3',
            )}
          >
            {!isAgentSpawn && <p className="text-sm text-(--color-text)">{q.question}</p>}
            {isAgentSpawn && spawnSelection ? (
              <div className="space-y-2">
                <div className="rounded-lg border border-(--color-border) bg-(--bg-card) p-2">
                  <button
                    type="button"
                    aria-expanded={modelPickerOpen}
                    onClick={() => setModelPickerOpen((open) => !open)}
                    className="flex h-7 w-full items-center justify-between gap-3 rounded-md px-1.5 text-left transition-colors hover:bg-(--bg-key)"
                  >
                    <span className="text-[11px] font-medium text-(--color-text-muted)">Model</span>
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span className="truncate font-mono text-xs text-(--color-text)">
                        {normalizeModelId(spawnSelection.model)
                          ? shortModelName(spawnSelection.model)
                          : 'Default'}
                      </span>
                      <ChevronDown
                        size={13}
                        aria-hidden="true"
                        className={cn(
                          'shrink-0 text-(--color-text-muted) transition-transform',
                          modelPickerOpen && 'rotate-180',
                        )}
                      />
                    </span>
                  </button>
                  <AnimatePresence initial={false}>
                    {modelPickerOpen && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={preset.spring}
                        className="overflow-hidden pt-1.5"
                      >
                        <ModelOptions
                          models={registry.data?.models ?? []}
                          selectedModel={spawnSelection.model}
                          limit={20}
                          listClassName="max-h-28"
                          onSelect={(modelId) => {
                            const nextModel = registry.data?.models.find((model) => model.id === modelId)
                            setSpawnSelection(
                              modelId,
                              reconcileThinkingLevel(spawnSelection.thinkingLevel, nextModel),
                            )
                            setModelPickerOpen(false)
                          }}
                        />
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>

                <div className="flex items-center gap-2 rounded-lg border border-(--color-border) bg-(--bg-card) p-2">
                  <p className="shrink-0 text-[11px] font-medium text-(--color-text-muted)">Thinking</p>
                  <div
                    className="flex min-w-0 flex-1 gap-1 overflow-x-auto overscroll-contain pb-0.5"
                    role="radiogroup"
                    aria-label="Agent thinking effort"
                  >
                    {thinkingOptions.map((option) => {
                      const selected = option.value === spawnSelection.thinkingLevel
                      return (
                        <button
                          key={option.value ?? '__default__'}
                          type="button"
                          role="radio"
                          aria-checked={selected}
                          disabled={replying}
                          onClick={() => setSpawnSelection(spawnSelection.model, option.value)}
                          className={cn(
                            'flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-[11px] transition-colors',
                            selected
                              ? 'border-(--color-primary) bg-(--color-primary)/10 text-(--color-text)'
                              : 'border-(--color-border) text-(--color-text-muted) hover:bg-(--bg-key)',
                          )}
                        >
                          <span
                            className="size-1.5 rounded-full"
                            style={{ backgroundColor: thinkingColor(option.value) }}
                            aria-hidden="true"
                          />
                          {option.label}
                        </button>
                      )
                    })}
                  </div>
                </div>
              </div>
            ) : options.length > 0 && (
              <div className="flex flex-wrap gap-1.5" role="group" aria-label="Suggested answers">
                {options.map((option) => (
                  <button
                    key={option}
                    type="button"
                    disabled={replying}
                    onClick={() => setAnswer(option)}
                    aria-pressed={answers[step] === option}
                    className={cn(
                      'rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)',
                      answers[step] === option
                        ? 'border-(--color-primary) bg-(--color-primary) text-(--color-text-on-accent)'
                        : 'border-(--color-border) bg-(--bg-card) text-(--color-text) hover:bg-(--bg-key)',
                      replying && 'pointer-events-none opacity-50',
                    )}
                  >
                    {option}
                  </button>
                ))}
              </div>
            )}
            {!isAgentSpawn && allowsFreeText && <input
              type="text"
              value={answers[step] ?? ''}
              onChange={(e) => setAnswer(e.target.value)}
              onKeyDown={(e) => {
                if (e.key !== 'Enter' || !currentAnswered) return
                if (isLast) void handleSend()
                else goToStep(step + 1)
              }}
              disabled={replying}
              placeholder={options.length > 0 ? 'Or type your own answer…' : 'Type your answer…'}
              aria-label={q.question}
              className="h-8 w-full rounded-md border border-(--color-border) bg-(--bg-card) px-2.5 text-xs text-(--color-text) outline-none focus:border-(--color-primary)"
              autoFocus
            />}
          </motion.div>
        </AnimatePresence>

        <div className={cn(
          'flex items-center justify-between gap-3 border-t border-(--color-border)',
          isAgentSpawn ? 'px-3 py-2' : 'px-4 py-2.5',
        )}>
          {isAgentSpawn ? (
            <button
              type="button"
              disabled={replying}
              onClick={() => void handleSend(['__cancel__'])}
              className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs font-medium text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            >
              <X size={13} aria-hidden="true" />
              Cancel
            </button>
          ) : (
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
          )}

          {replyError && (
            <p className="text-xs text-red-600 dark:text-red-400" role="alert">{replyError}</p>
          )}

          {isLast ? (
            <button
              type="button"
              disabled={replying || !allAnswered}
              onClick={() => void handleSend()}
              className={cn(
                'flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors',
                'bg-(--color-primary) text-(--color-text-on-accent) hover:opacity-90',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)',
                (replying || !allAnswered) && 'pointer-events-none opacity-50',
              )}
            >
              <Send size={12} aria-hidden="true" />
              {replying ? 'Sending…' : isAgentSpawn ? 'Spawn agent' : 'Submit'}
            </button>
          ) : (
            <button
              type="button"
              disabled={!currentAnswered}
              onClick={() => goToStep(step + 1)}
              className={cn(
                'flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors',
                'bg-(--color-primary) text-(--color-text-on-accent) hover:opacity-90',
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
