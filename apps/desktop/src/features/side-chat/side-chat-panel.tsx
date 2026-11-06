import * as React from "react";
import { ArrowUpIcon, CheckIcon, CopyIcon, MessageSquarePlusIcon, SquareIcon } from "lucide-react";
import { SideChatIcon } from "@/components/icons/tool-icons";
import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";
import { EMPTY_SIDE_THREAD, useSideChatStore, type SideTurn } from "@/stores/side-chat-store";
import { useUiStore } from "@/stores/ui-store";

const SUGGESTIONS = ["Summarize what happened so far", "What is the agent doing right now?", "Which files were changed?"];

function IconButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick(): void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={label}
            disabled={disabled}
            onClick={onClick}
            className="shrink-0 text-muted-foreground"
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <IconButton
      label={copied ? "Copied" : "Copy answer"}
      onClick={() => {
        void navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
    >
      {copied ? <CheckIcon /> : <CopyIcon />}
    </IconButton>
  );
}

function Turn({ turn }: { turn: SideTurn }) {
  const writing = turn.status === "running" || turn.status === "queued";
  return (
    <div className="flex flex-col gap-2">
      <div className="ml-8 self-end rounded-2xl bg-muted px-3 py-1.5 text-sm leading-6 whitespace-pre-wrap dark:bg-accent/60" data-selectable>
        {turn.question}
      </div>
      <div className="group/answer flex flex-col gap-1">
        {turn.text ? (
          <Markdown streaming={writing}>{turn.text}</Markdown>
        ) : writing ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner className="size-3.5" />
            {turn.status === "queued" ? "Waiting…" : "Thinking…"}
          </div>
        ) : null}
        {turn.status === "failed" && (
          <p className="text-xs text-destructive">{turn.error || "The answer failed."}</p>
        )}
        {turn.status === "cancelled" && <p className="text-xs text-muted-foreground">Stopped.</p>}
        {turn.status === "done" && turn.text && (
          <div className="flex opacity-0 transition-opacity group-hover/answer:opacity-100 focus-within:opacity-100">
            <CopyButton text={turn.text} />
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * The Side chat tool: ask about the active chat without interrupting it. The
 * answer reads everything the chat has seen so far, runs no tools and adds
 * nothing to the chat; follow-ups keep the thread. Threads live in the
 * engine's memory, one per chat, and end with it.
 */
export function SideChatPanel() {
  const chat = useEngineStore((s) => s.activeId);
  const status = useEngineStore((s) => s.status);
  const thread = useSideChatStore((s) => (chat ? s.threads[chat] : undefined)) ?? EMPTY_SIDE_THREAD;
  const error = useSideChatStore((s) => (chat ? s.errors[chat] : undefined));
  const draft = useSideChatStore((s) => (chat ? (s.drafts[chat] ?? "") : ""));
  const { ask, stop, clear, setDraft, refresh } = useSideChatStore.getState();
  const input = React.useRef<HTMLTextAreaElement>(null);
  const scroller = React.useRef<HTMLDivElement>(null);
  const ready = status === "ready";
  const writing = thread.queued.length > 0 || thread.turns.some((t) => t.status === "running" || t.status === "queued");
  const lastText = thread.turns.at(-1)?.text ?? "";

  // The thread of the chat on screen, and focus on the question box.
  React.useEffect(() => {
    void refresh();
    input.current?.focus();
  }, [chat, ready, refresh]);

  // Follow the answer while it streams, unless scrolled up.
  const pinned = React.useRef(true);
  React.useLayoutEffect(() => {
    const element = scroller.current;
    if (element && pinned.current) element.scrollTop = element.scrollHeight;
  }, [thread.turns.length, lastText, thread.queued.length]);

  const send = (text = draft) => {
    if (!chat || !ready || !text.trim()) return;
    pinned.current = true;
    void ask(text);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-9 shrink-0 items-center gap-1 border-b border-border/60 pr-1.5 pl-3">
        <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          Reads this chat · no tools · not added to the chat
        </span>
        {writing && (
          <IconButton label="Stop" onClick={() => void stop()}>
            <SquareIcon className="fill-current" />
          </IconButton>
        )}
        <IconButton
          label="New side chat"
          disabled={thread.turns.length === 0 && !writing}
          onClick={() => {
            void clear();
            input.current?.focus();
          }}
        >
          <MessageSquarePlusIcon />
        </IconButton>
      </div>

      <div
        ref={scroller}
        onScroll={(event) => {
          const element = event.currentTarget;
          pinned.current = element.scrollHeight - element.scrollTop - element.clientHeight < 24;
        }}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-4"
      >
        {thread.turns.length === 0 ? (
          <Empty className="h-full">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <SideChatIcon />
              </EmptyMedia>
              <EmptyTitle>Ask on the side</EmptyTitle>
              <EmptyDescription>
                A quick question about this chat while it keeps working. The answer uses what the chat has seen so
                far; nothing runs and nothing is added to the chat.
              </EmptyDescription>
            </EmptyHeader>
            <div className="flex flex-col items-center gap-1.5">
              {SUGGESTIONS.map((suggestion) => (
                <Button key={suggestion} size="xs" variant="outline" disabled={!ready} onClick={() => send(suggestion)}>
                  {suggestion}
                </Button>
              ))}
            </div>
          </Empty>
        ) : (
          <div className="flex flex-col gap-5">
            {thread.historyTruncated && (
              <p className="text-center text-xs text-muted-foreground">Earlier questions were dropped.</p>
            )}
            {thread.turns.map((turn) => (
              <Turn key={turn.requestId} turn={turn} />
            ))}
            {thread.queued.map((question, index) => (
              <div
                key={`queued-${index}`}
                className="ml-8 self-end rounded-2xl border border-dashed border-border px-3 py-1.5 text-sm text-muted-foreground"
              >
                {question}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="shrink-0 px-3 pb-3">
        {error && <p className="mb-1.5 px-1 text-xs text-destructive">{error}</p>}
        <div
          className={cn(
            "flex items-end gap-1.5 rounded-xl bg-muted/70 py-1.5 pr-1.5 pl-3 ring-1 ring-transparent focus-within:ring-ring/40 dark:bg-accent/50",
            !ready && "opacity-60",
          )}
        >
          <textarea
            ref={input}
            rows={1}
            value={draft}
            disabled={!chat}
            onChange={(event) => chat && setDraft(chat, event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                send();
              } else if (event.key === "Escape") {
                event.preventDefault();
                if (writing) void stop();
                else useUiStore.getState().toggleRightPanel(false);
              }
            }}
            placeholder={ready ? (thread.turns.length ? "Ask a follow-up" : "Ask about this chat") : "Waiting for the engine…"}
            aria-label="Side question"
            // Grows with its text up to a few lines; sized by CSS, so it follows
            // the panel's width as it slides open (a one-time measure did not).
            className="field-sizing-content max-h-40 min-h-6 flex-1 resize-none bg-transparent py-0.5 text-sm leading-6 shadow-none outline-none placeholder:text-muted-foreground focus-visible:shadow-none"
          />
          <Button
            size="icon-sm"
            aria-label="Ask"
            disabled={!ready || !draft.trim()}
            onClick={() => send()}
            className="shrink-0 rounded-lg"
          >
            <ArrowUpIcon />
          </Button>
        </div>
      </div>
    </div>
  );
}
