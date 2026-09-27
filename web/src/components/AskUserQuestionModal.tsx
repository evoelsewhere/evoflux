/**
 * AskUserQuestionModal — floating bar (same slot as PermissionApprovalModal,
 * right above the input) showing one clarifying question at a time from the
 * batch the agent asked via the `ask_user` tool. Step through with
 * next/back; the last question shows Submit instead of Next. Suggested
 * answers are a numbered list — the digit keys pick one — with a free-text
 * row underneath.
 */
import { forwardRef, useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, ChevronLeft } from 'lucide-react'
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

const KBD_CLASS =
  'hidden h-4.5 min-w-4.5 items-center justify-center rounded-[4px] border border-current/25 px-1 font-sans text-[10px] leading-none opacity-70 sm:inline-flex'

const GHOST_BUTTON = cn(
  'flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium text-(--color-text-muted) transition-colors',
  'hover:bg-(--bg-key) hover:text-(--color-text)',
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)',
)

const PRIMARY_BUTTON = cn(
  'flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors',
  'bg-(--color-primary) text-(--color-text-on-accent) hover:opacity-90',
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring) focus-visible:ring-offset-1 focus-visible:ring-offset-(--bg-card)',
)

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
  const cardRef = useRef<HTMLDivElement>(null)

  const q = questions[step]
  const hasOptions = (q?.options.length ?? 0) > 0

  // With suggestions on screen, focus the card so the digit keys pick one.
  // A question with no suggestions autofocuses its text field on mount
  // instead — the step body mounts only after the previous one exits.
  useEffect(() => {
    if (!hasOptions) return
    const frame = requestAnimationFrame(() => cardRef.current?.focus({ preventScroll: true }))
    return () => cancelAnimationFrame(frame)
  }, [step, hasOptions])

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

  const handleCardKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    // Typing belongs to the text field, and a focused button handles its own
    // Enter; only keys pressed on the card itself are shortcuts.
    if (e.target !== e.currentTarget || replying || isAgentSpawn) return
    const digit = Number.parseInt(e.key, 10)
    if (digit >= 1 && digit <= Math.min(options.length, 9)) {
      e.preventDefault()
      setAnswer(options[digit - 1])
      return
    }
    if (e.key === 'Enter' && currentAnswered) {
      e.preventDefault()
      if (isLast) {
        if (allAnswered) void handleSend()
      } else {
        goToStep(step + 1)
      }
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
      <div
        ref={cardRef}
        tabIndex={-1}
        onKeyDown={handleCardKeyDown}
        className="overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-card) shadow-(--shadow-depth) outline-none"
      >
        <AnimatePresence mode="wait">
          <motion.div
            key={step}
            initial={{ opacity: 0, x: 8 * preset.distance }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -8 * preset.distance }}
            transition={preset.spring}
            className="px-4 pb-3 pt-3.5"
          >
            <div className="flex items-baseline justify-between gap-3">
              <p className="min-w-0 text-sm font-medium whitespace-pre-wrap text-(--color-text)">
                {spawnSpec ? `Spawn ${spawnSpec.blueprint}` : q.question}
              </p>
              {questions.length > 1 && (
                <span className="shrink-0 text-[11px] tabular-nums text-(--color-text-subtle)">
                  {step + 1} / {questions.length}
                </span>
              )}
            </div>
            {isAgentSpawn && spawnSelection ? (
              <div className="mt-2.5 space-y-2">
                <div className="rounded-lg border border-(--color-border-subtle) bg-(--bg-page) p-1.5">
                  <button
                    type="button"
                    aria-expanded={modelPickerOpen}
                    onClick={() => setModelPickerOpen((open) => !open)}
                    className="flex h-7 w-full items-center justify-between gap-3 rounded-md px-1.5 text-left transition-colors hover:bg-(--bg-key)"
                  >
                    <span className="text-[11px] font-medium text-(--color-text-muted)">Model</span>
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span className="truncate font-mono text-xs text-(--color-text)">
                        {shortModelName(spawnSelection.model)}
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

                <div className="flex items-center gap-2 rounded-lg border border-(--color-border-subtle) bg-(--bg-page) p-1.5 pl-3">
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
                              ? 'border-(--color-border-strong) bg-(--bg-key) text-(--color-text)'
                              : 'border-transparent text-(--color-text-muted) hover:bg-(--bg-key)',
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
            ) : (
              <div className="mt-2.5 flex flex-col gap-0.5">
                {options.length > 0 && (
                  <div className="flex flex-col gap-0.5" role="group" aria-label="Suggested answers">
                    {options.map((option, index) => {
                      const selected = answers[step] === option
                      return (
                        <button
                          key={option}
                          type="button"
                          disabled={replying}
                          onClick={() => setAnswer(option)}
                          aria-pressed={selected}
                          className={cn(
                            'group flex min-h-8 w-full items-center gap-2.5 rounded-lg px-2 py-1 text-left text-[13px] transition-colors',
                            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)',
                            selected
                              ? 'bg-(--bg-key) text-(--color-text)'
                              : 'text-(--color-text-2) hover:bg-(--bg-key)/60 hover:text-(--color-text)',
                            replying && 'pointer-events-none opacity-50',
                          )}
                        >
                          <span
                            aria-hidden="true"
                            className={cn(
                              'flex size-5 shrink-0 items-center justify-center rounded-[5px] border text-[11px] tabular-nums transition-colors',
                              selected
                                ? 'border-(--color-text) bg-(--color-text) text-(--bg-card)'
                                : 'border-(--color-border) text-(--color-text-muted)',
                            )}
                          >
                            {index < 9 ? index + 1 : '·'}
                          </span>
                          <span className="min-w-0 flex-1">{option}</span>
                          {selected && <Check size={14} aria-hidden="true" className="shrink-0 text-(--color-text-muted)" />}
                        </button>
                      )
                    })}
                  </div>
                )}
                <div
                  className={cn(
                    'flex items-center gap-2.5 rounded-lg border px-2 transition-colors',
                    options.length > 0
                      ? 'border-transparent focus-within:border-(--color-border) focus-within:bg-(--bg-page)'
                      : 'border-(--color-border) bg-(--bg-page) focus-within:border-(--color-border-strong)',
                  )}
                >
                  {options.length > 0 && (
                    <span
                      aria-hidden="true"
                      className="flex size-5 shrink-0 items-center justify-center rounded-[5px] border border-dashed border-(--color-border) text-[11px] text-(--color-text-subtle)"
                    >
                      …
                    </span>
                  )}
                  <input
                    type="text"
                    autoFocus={options.length === 0}
                    // A picked suggestion is shown by its row, not echoed here.
                    value={options.includes(answers[step] ?? '') ? '' : answers[step] ?? ''}
                    onChange={(e) => setAnswer(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key !== 'Enter' || !currentAnswered) return
                      e.stopPropagation()
                      if (isLast) void handleSend()
                      else goToStep(step + 1)
                    }}
                    disabled={replying}
                    placeholder={options.length > 0 ? 'Or type your own answer…' : 'Type your answer…'}
                    aria-label={q.question}
                    className="h-8 min-w-0 flex-1 bg-transparent text-[13px] text-(--color-text) outline-none placeholder:text-(--color-text-subtle)"
                  />
                </div>
              </div>
            )}
          </motion.div>
        </AnimatePresence>

        <div className="flex items-center gap-2 border-t border-(--color-border-subtle) px-3 py-2">
          {isAgentSpawn ? (
            <button
              type="button"
              disabled={replying}
              onClick={() => void handleSend(['__cancel__'])}
              className={cn(GHOST_BUTTON, replying && 'pointer-events-none opacity-50')}
            >
              Cancel
            </button>
          ) : step > 0 ? (
            <button
              type="button"
              disabled={replying}
              onClick={() => goToStep(step - 1)}
              className={cn(GHOST_BUTTON, 'pl-1.5', replying && 'pointer-events-none opacity-50')}
            >
              <ChevronLeft size={13} aria-hidden="true" />
              Back
            </button>
          ) : null}

          <p className="min-w-0 flex-1 truncate px-1 text-xs text-(--color-danger)" role={replyError ? 'alert' : undefined}>
            {replyError}
          </p>

          {isLast ? (
            <button
              type="button"
              disabled={replying || !allAnswered}
              onClick={() => void handleSend()}
              className={cn(PRIMARY_BUTTON, (replying || !allAnswered) && 'pointer-events-none opacity-50')}
            >
              {replying ? 'Sending…' : isAgentSpawn ? 'Spawn agent' : 'Submit'}
              {!replying && <kbd aria-hidden="true" className={KBD_CLASS}>↵</kbd>}
            </button>
          ) : (
            <button
              type="button"
              disabled={!currentAnswered}
              onClick={() => goToStep(step + 1)}
              className={cn(PRIMARY_BUTTON, !currentAnswered && 'pointer-events-none opacity-50')}
            >
              Next
              <kbd aria-hidden="true" className={KBD_CLASS}>↵</kbd>
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
