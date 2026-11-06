import * as React from "react";
import { CheckIcon, ChevronDownIcon, CopyIcon, FileIcon, FileTextIcon, PencilIcon } from "lucide-react";
import { MessageAction } from "@/components/ai-elements/message-action";
import { FileLink } from "@/components/ai-elements/file-link";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Button } from "@/components/ui/button";
import { Message, MessageContent, MessageFooter } from "@/components/ui/message";
import { fileName } from "@/features/files/fs";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";
import { splitPrompt } from "./composer-input";
import type { Turn } from "./transcript";

/** Pasted text sent with the message: a chip that unfolds to show it. */
function PastedText({ lines, text }: { lines: number; text: string }) {
  const [open, setOpen] = React.useState(false);
  return (
    <div className="flex max-w-full min-w-0 flex-col items-end">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-lg border border-border/70 bg-card px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
      >
        <FileTextIcon className="size-3.5" />
        Pasted text · {lines} {lines === 1 ? "line" : "lines"}
        <ChevronDownIcon className={cn("size-3.5 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <pre
          data-selectable
          className="scrollbar-slim mt-1 max-h-72 max-w-full overflow-auto rounded-lg border border-border/70 bg-card p-2 font-mono text-[11.5px] whitespace-pre-wrap"
        >
          {text}
        </pre>
      )}
    </div>
  );
}

/** The message text, with a leading `/command` shown as a token like in the composer. */
function PromptText({ text }: { text: string }) {
  const command = /^\/([A-Za-z0-9_:.-]+)(?=\s|$)/.exec(text);
  if (!command) return <>{text}</>;
  return (
    <>
      <span className="rounded-[4px] bg-brand/14 font-medium text-brand ring-2 ring-brand/14">{command[0]}</span>
      {text.slice(command[0].length)}
    </>
  );
}

/** Edit a sent message in place; sending it reruns the chat from there. */
function EditPrompt({ initial, onCancel, onSend }: { initial: string; onCancel(): void; onSend(text: string): void }) {
  const [text, setText] = React.useState(initial);
  const ref = React.useRef<HTMLTextAreaElement>(null);
  React.useEffect(() => {
    const field = ref.current;
    if (!field) return;
    field.focus();
    field.setSelectionRange(field.value.length, field.value.length);
  }, []);
  const canSend = text.trim().length > 0;
  return (
    <div className="flex w-full max-w-[85%] flex-col gap-2 self-end rounded-2xl border border-border bg-card p-2 shadow-border-small">
      <textarea
        ref={ref}
        value={text}
        aria-label="Edit message"
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            onCancel();
          } else if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            if (canSend) onSend(text);
          }
        }}
        rows={Math.min(12, Math.max(2, text.split("\n").length))}
        className="scrollbar-slim w-full resize-none bg-transparent px-1.5 py-1 text-sm shadow-none outline-none focus-visible:shadow-none"
      />
      <div className="flex items-center justify-end gap-2">
        <span className="mr-auto px-1.5 text-[11px] text-muted-foreground">The reply and what followed are replaced.</span>
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button size="sm" disabled={!canSend} onClick={() => onSend(text)}>
          Send
        </Button>
      </div>
    </div>
  );
}

/** The person's message: pictures, text, pasted text and attached files, with Copy and Edit. */
export function UserPrompt({ turn }: { turn: Turn }) {
  const busy = useEngineStore((s) => s.transcript.busy);
  const [copied, setCopied] = React.useState(false);
  const [editing, setEditing] = React.useState(false);
  const [problem, setProblem] = React.useState<string | null>(null);
  const { text, pasted, files } = React.useMemo(() => splitPrompt(turn.prompt), [turn.prompt]);
  const images = turn.images ?? [];

  React.useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  if (editing) {
    return (
      <Message align="end">
        <MessageContent className="w-full">
          <EditPrompt
            initial={turn.prompt}
            onCancel={() => setEditing(false)}
            onSend={(next) => {
              setEditing(false);
              setProblem(null);
              void useEngineStore
                .getState()
                .editMessage(turn.id, next)
                .catch((error) => setProblem(error instanceof Error ? error.message : String(error)));
            }}
          />
        </MessageContent>
      </Message>
    );
  }

  return (
    <Message align="end" className="group/prompt">
      <MessageContent className="items-end gap-1.5">
        {images.length > 0 && (
          <div className="flex flex-wrap justify-end gap-1.5">
            {images.map((src, index) => (
              <a
                key={index}
                href={src}
                target="_blank"
                rel="noreferrer"
                className="overflow-hidden rounded-xl border border-border/70 bg-card"
                title="Open the picture"
              >
                <img src={src} alt={`Picture ${index + 1}`} className="max-h-48 max-w-64 object-contain" />
              </a>
            ))}
          </div>
        )}
        {text && (
          <Bubble align="end" variant="muted">
            <BubbleContent className="whitespace-pre-wrap" data-selectable>
              <PromptText text={text} />
            </BubbleContent>
          </Bubble>
        )}
        {pasted.map((block, index) => (
          <PastedText key={index} lines={block.lines} text={block.text} />
        ))}
        {files.length > 0 && (
          <div className="flex flex-wrap justify-end gap-1.5">
            {files.map((path) => (
              <span
                key={path}
                title={path}
                className="flex max-w-64 items-center gap-1.5 rounded-lg border border-border/70 bg-card px-2 py-1 text-xs text-muted-foreground"
              >
                <FileIcon className="size-3.5 shrink-0" />
                <FileLink path={path} label={fileName(path)} className="truncate" />
              </span>
            ))}
          </div>
        )}
        {problem && <p className="text-xs text-destructive">{problem}</p>}
        <MessageFooter className="gap-0.5 px-0 opacity-0 transition-opacity group-focus-within/prompt:opacity-100 group-hover/prompt:opacity-100">
          <MessageAction
            label={copied ? "Copied" : "Copy"}
            onClick={() => {
              void navigator.clipboard.writeText([text, ...pasted.map((block) => block.text)].filter(Boolean).join("\n\n"));
              setCopied(true);
            }}
          >
            {copied ? <CheckIcon /> : <CopyIcon />}
          </MessageAction>
          <MessageAction
            label={busy ? "Edit (when the agent is done)" : "Edit"}
            disabled={busy}
            onClick={() => setEditing(true)}
          >
            <PencilIcon />
          </MessageAction>
        </MessageFooter>
      </MessageContent>
    </Message>
  );
}
