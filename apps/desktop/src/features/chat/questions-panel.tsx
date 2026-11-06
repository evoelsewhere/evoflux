import * as React from "react";
import { CheckIcon, MessageCircleQuestionIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { StatusDot } from "@/components/status-dot";
import { modKey } from "@/lib/platform";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";
import type { PermissionRequest, Question } from "./transcript";

// The agent's questions (`ask_user`) take the chat input's place until they are
// answered: one card per question, options to pick (one, or several), and a
// field for an answer in your own words. Submit sends them all; Skip tells the
// agent to decide itself.

interface Answer {
  selected: string[];
  other: string;
}

function QuestionCard({
  question,
  index,
  answer,
  onChange,
}: {
  question: Question;
  index: number;
  answer: Answer;
  /** Updates from the latest answer, so quick picks are never lost. */
  onChange(update: (current: Answer) => Answer): void;
}) {
  const pick = (label: string) =>
    onChange((current) => {
      if (question.multiSelect) {
        const on = current.selected.includes(label);
        return { ...current, selected: on ? current.selected.filter((x) => x !== label) : [...current.selected, label] };
      }
      return { selected: current.selected[0] === label ? [] : [label], other: "" };
    });
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
                    {index === 0 && i < 9 ? <span className="mr-1.5 text-muted-foreground tabular-nums">{i + 1}</span> : null}
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
  const ready = answers.every((a) => a.selected.length > 0 || a.other.trim());
  const submit = React.useCallback(() => {
    if (!ready) return;
    void answerQuestions(
      permission.requestId,
      answers.map((a) => ({ selected: a.selected, other: a.other.trim() || undefined })),
    );
  }, [answerQuestions, answers, permission.requestId, ready]);

  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing) return;
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        submit();
        return;
      }
      // Digits pick the first question's options while no field has focus.
      const typing = document.activeElement?.tagName === "INPUT" || document.activeElement?.tagName === "TEXTAREA";
      const first = questions[0];
      if (!typing && first && /^[1-9]$/.test(event.key)) {
        const option = first.options[Number(event.key) - 1];
        if (!option) return;
        event.preventDefault();
        setAnswers((all) =>
          all.map((a, i) => {
            if (i !== 0) return a;
            if (first.multiSelect) {
              const on = a.selected.includes(option.label);
              return { ...a, selected: on ? a.selected.filter((x) => x !== option.label) : [...a.selected, option.label] };
            }
            return { selected: [option.label], other: "" };
          }),
        );
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [questions, submit]);

  return (
    <div className="flex flex-col gap-2" role="dialog" aria-label="Questions from the agent">
      <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
        <StatusDot tone="info" pulse />
        The agent has {questions.length === 1 ? "a question" : `${questions.length} questions`}
        <span className="ml-auto flex items-center gap-1.5">
          <Kbd>{modKey}+Enter</Kbd> send
        </span>
      </div>
      <div className="flex max-h-[60vh] flex-col gap-5 overflow-y-auto rounded-2xl border border-border bg-background p-4 shadow-xs">
        <div className="flex items-center gap-2 text-xs font-medium text-brand">
          <MessageCircleQuestionIcon className="size-4" /> Questions
        </div>
        {questions.map((question, index) => (
          <QuestionCard
            key={index}
            question={question}
            index={index}
            answer={answers[index]}
            onChange={(update) => setAnswers((all) => all.map((a, i) => (i === index ? update(a) : a)))}
          />
        ))}
        <div className="flex items-center justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={() => void answerQuestions(permission.requestId, null)}>
            Skip — let the agent decide
          </Button>
          <Button size="sm" disabled={!ready} onClick={submit}>
            Send answers
          </Button>
        </div>
      </div>
    </div>
  );
}
