import * as React from "react";
import { CheckIcon, MessageCircleQuestionIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { StatusDot } from "@/components/status-dot";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";
import type { PermissionRequest, Question } from "./transcript";

// The agent's questions (`ask_user`) take the chat input's place until they are
// answered, one question per step: options to pick (one, or several) and a
// field for an answer in your own words. Picking a single-choice option moves
// on; Back / Next (Enter) step through, a chip per question jumps to it, and
// Send on the last step (or Ctrl+Enter once all are answered) sends them all.
// Skip tells the agent to decide itself.

interface Answer {
  selected: string[];
  other: string;
}

const answered = (a: Answer) => a.selected.length > 0 || a.other.trim().length > 0;

/** `label` toggled in `current` for `question`. */
function toggle(question: Question, current: Answer, label: string): Answer {
  if (question.multiSelect) {
    const on = current.selected.includes(label);
    return { ...current, selected: on ? current.selected.filter((x) => x !== label) : [...current.selected, label] };
  }
  return { selected: current.selected[0] === label ? [] : [label], other: "" };
}

function QuestionCard({
  question,
  answer,
  onChange,
  onPicked,
}: {
  question: Question;
  answer: Answer;
  /** Updates from the latest answer, so quick picks are never lost. */
  onChange(update: (current: Answer) => Answer): void;
  /** A single-choice option was picked. */
  onPicked(): void;
}) {
  const pick = (label: string) => {
    const choosing = !question.multiSelect && answer.selected[0] !== label;
    onChange((current) => toggle(question, current, label));
    if (choosing) onPicked();
  };
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-2 flex w-full items-start gap-2">
        {question.header && (
          <span className="mt-0.5 shrink-0 rounded bg-brand/12 px-1.5 text-[11px] leading-5 text-brand">{question.header}</span>
        )}
        <span className="text-[13.5px] font-medium leading-6">{question.question}</span>
      </legend>
      {question.options.length > 0 && (
        <div className="flex flex-col gap-1">
          {question.options.map((option, i) => {
            const on = answer.selected.includes(option.label);
            return (
              <button
                key={option.label}
                type="button"
                role={question.multiSelect ? "checkbox" : "radio"}
                aria-checked={on}
                onClick={() => pick(option.label)}
                className={cn(
                  "flex items-start gap-2.5 rounded-lg px-2.5 py-2 text-left ring-1 transition-colors",
                  on ? "bg-brand/10 ring-brand/50" : "ring-border hover:bg-accent/60",
                )}
              >
                <span
                  className={cn(
                    "mt-0.5 flex size-4 shrink-0 items-center justify-center border",
                    question.multiSelect ? "rounded" : "rounded-full",
                    on ? "border-brand bg-brand text-brand-foreground" : "border-muted-foreground/50",
                  )}
                >
                  {on && <CheckIcon className="size-3" />}
                </span>
                <span className="flex min-w-0 flex-col">
                  <span className="text-[13px]">
                    {i < 9 ? <span className="mr-1.5 text-muted-foreground tabular-nums">{i + 1}</span> : null}
                    {option.label}
                  </span>
                  {option.description && <span className="text-xs text-muted-foreground">{option.description}</span>}
                </span>
              </button>
            );
          })}
        </div>
      )}
      <input
        value={answer.other}
        onChange={(e) => {
          const other = e.target.value;
          onChange((current) => ({ selected: question.multiSelect || !other ? current.selected : [], other }));
        }}
        placeholder={question.options.length ? "Or answer in your own words" : "Your answer"}
        aria-label={`Answer to: ${question.question}`}
        className="h-8 rounded-lg border border-border bg-background px-2.5 text-[13px] outline-none focus-visible:border-brand"
      />
    </fieldset>
  );
}

export function QuestionsPanel({ permission }: { permission: PermissionRequest }) {
  const answerQuestions = useEngineStore((s) => s.answerQuestions);
  const questions = permission.questions ?? [];
  const [answers, setAnswers] = React.useState<Answer[]>(() => questions.map(() => ({ selected: [], other: "" })));
  const [step, setStep] = React.useState(0);
  const count = questions.length;
  const last = step >= count - 1;
  const question = questions[step];
  const ready = answers.every(answered);
  const current = answers[step];

  const submit = React.useCallback(() => {
    if (!ready) return;
    void answerQuestions(
      permission.requestId,
      answers.map((a) => ({ selected: a.selected, other: a.other.trim() || undefined })),
    );
  }, [answerQuestions, answers, permission.requestId, ready]);

  /** The next step, or sending when this is the last one. */
  const next = React.useCallback(() => {
    if (!current || !answered(current)) return;
    if (last) submit();
    else setStep((s) => Math.min(s + 1, count - 1));
  }, [count, current, last, submit]);

  // A single-choice pick moves on after a beat, so the choice is seen first.
  const advance = React.useRef<number | undefined>(undefined);
  const pickedOne = React.useCallback(() => {
    if (last) return;
    window.clearTimeout(advance.current);
    const from = step;
    advance.current = window.setTimeout(() => setStep((s) => (s === from ? Math.min(s + 1, count - 1) : s)), 180);
  }, [count, last, step]);
  React.useEffect(() => () => window.clearTimeout(advance.current), []);

  const update = React.useCallback(
    (change: (current: Answer) => Answer) => setAnswers((all) => all.map((a, i) => (i === step ? change(a) : a))),
    [step],
  );

  const panel = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing || !question) return;
      const active = document.activeElement;
      const typing = active?.tagName === "INPUT" || active?.tagName === "TEXTAREA";
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        if (ready) submit();
        else next();
        return;
      }
      // Plain Enter steps on while focus is in the panel (or nowhere), except
      // on a focused button, which it presses.
      const here = !active || active === document.body || !!panel.current?.contains(active);
      if (
        event.key === "Enter" &&
        here &&
        !event.shiftKey &&
        !event.altKey &&
        !event.ctrlKey &&
        !event.metaKey &&
        active?.tagName !== "BUTTON"
      ) {
        event.preventDefault();
        next();
        return;
      }
      if (typing) return;
      // Digits pick the shown question's options.
      if (/^[1-9]$/.test(event.key)) {
        const option = question.options[Number(event.key) - 1];
        if (!option) return;
        event.preventDefault();
        const choosing = !question.multiSelect && current?.selected[0] !== option.label;
        update((a) => toggle(question, a, option.label));
        if (choosing) pickedOne();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, next, pickedOne, question, ready, submit, update]);

  if (!question || !current) return null;

  return (
    <div ref={panel} className="flex flex-col gap-2" role="dialog" aria-label="Questions from the agent">
      <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
        <StatusDot tone="info" pulse />
        The agent has {count === 1 ? "a question" : `${count} questions`}
        <span className="ml-auto flex items-center gap-1.5">
          <Kbd>Enter</Kbd> {last ? "send" : "next"}
        </span>
      </div>
      <div className="flex flex-col gap-4 rounded-2xl border border-border bg-background p-4 shadow-xs">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex shrink-0 items-center gap-1.5 text-xs font-medium text-brand">
            <MessageCircleQuestionIcon className="size-4" />
            {count > 1 ? `${step + 1} of ${count}` : "Question"}
          </span>
          {count > 1 && (
            <div role="tablist" aria-label="Questions" className="flex min-w-0 flex-1 gap-1 overflow-x-auto">
              {questions.map((q, i) => {
                const done = answered(answers[i]);
                return (
                  <button
                    key={i}
                    type="button"
                    role="tab"
                    aria-selected={i === step}
                    onClick={() => setStep(i)}
                    className={cn(
                      "flex h-6 max-w-40 shrink-0 items-center gap-1 rounded-md px-2 text-[11.5px] transition-colors",
                      i === step
                        ? "bg-accent text-foreground ring-1 ring-border"
                        : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                    )}
                  >
                    {done ? (
                      <CheckIcon className="size-3 shrink-0 text-brand" />
                    ) : (
                      <span className="tabular-nums">{i + 1}</span>
                    )}
                    <span className="truncate">{q.header || `Question ${i + 1}`}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
        <div className="max-h-[50vh] overflow-y-auto">
          <QuestionCard key={step} question={question} answer={current} onChange={update} onPicked={pickedOne} />
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="ghost" onClick={() => void answerQuestions(permission.requestId, null)}>
            Skip — let the agent decide
          </Button>
          <span className="ml-auto" />
          {step > 0 && (
            <Button size="sm" variant="outline" onClick={() => setStep((s) => Math.max(s - 1, 0))}>
              Back
            </Button>
          )}
          {last ? (
            <Button size="sm" disabled={!ready} onClick={submit}>
              Send answers
            </Button>
          ) : (
            <Button size="sm" disabled={!answered(current)} onClick={next}>
              Next
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
