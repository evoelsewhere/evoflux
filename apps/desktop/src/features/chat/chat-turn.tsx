import * as React from "react";
import { CheckIcon, ChevronRightIcon, CircleAlertIcon, CopyIcon, MessagesSquareIcon } from "lucide-react";
import { MessageAction } from "@/components/ai-elements/message-action";
import { Reasoning, seconds } from "@/components/ai-elements/reasoning";
import { Tool, activity, toolKind } from "@/components/ai-elements/tool";
import { Markdown } from "@/components/markdown";
import { AgentIcon } from "@/components/icons/agent-icon";
import { Message, MessageContent, MessageFooter } from "@/components/ui/message";
import { Spinner } from "@/components/ui/spinner";
import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceLine,
  TraceTitle,
} from "@/components/ui/trace";
import { formatCost, formatDuration, formatTokens } from "@/lib/format";
import { cn } from "@/lib/utils";
import { UserPrompt } from "./user-message";
import { SentFiles, type SentFile } from "@/components/ai-elements/sent-files";
import { isBackgroundNote, turnReply, type Part, type ReasoningPart, type ToolPart, type Turn } from "./transcript";

// One turn, mapped the way DeepSeek Harness maps it, on shadcn/ui AI Elements:
// - the person's text is a Bubble (Message);
// - the agent's parts keep the model's order; consecutive reasoning and tool
//   rows form a process group on Trace whose title names what is happening
//   while it runs ("Running commands") and summarises it after ("Read files
//   and ran commands");
// - text parts are the reply, as markdown, always visible;
// - once the turn completes its process folds behind "Completed in 1m 12s";
// - a running turn ends with a live "Working for 12s" line.

/** A background subagent's delivered report, or the automated wake that reads it. */
function BackgroundNote({ text }: { text: string }) {
  if (text.trimStart().startsWith("<mail")) {
    // A message or question from an agent, or the wake that reads them.
    const names = /^<mail-arrived>\s*(.*?) sent you/.exec(text.trimStart())?.[1];
    const title = /<mail [^>]*title="([^"]*)"/.exec(text)?.[1];
    const ask = /<mail [^>]*kind="ask"/.test(text);
    const label = names
      ? `Messages arrived · ${names.replace(/"/g, "")}`
      : `${ask ? "Question" : "Message"} from ${title ?? "an agent"}`;
    return (
      <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
        <span className="h-px flex-1 bg-border" />
        <MessagesSquareIcon className="size-3.5" />
        <span className="max-w-[70%] truncate">{label}</span>
        <span className="h-px flex-1 bg-border" />
      </div>
    );
  }
  if (text.trimStart().startsWith("<nested-session")) {
    // A note carries its title; the automated wake that reads notes lists them.
    const listed = /finished a turn: (.*?)\. (Its|Their) note/.exec(text)?.[1];
    const titles = listed
      ? [...listed.matchAll(/"([^"]*)"/g)].map((m) => m[1])
      : [...text.matchAll(/<nested-session [^>]*title="([^"]*)"/g)].map((m) => m[1]);
    const label =
      titles.length > 1
        ? `${titles.length} sessions finished a turn · ${titles.join(", ")}`
        : `Session finished a turn · ${titles[0] ?? ""}`;
    return (
      <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
        <span className="h-px flex-1 bg-border" />
        <MessagesSquareIcon className="size-3.5" />
        <span className="max-w-[70%] truncate">{label}</span>
        <span className="h-px flex-1 bg-border" />
      </div>
    );
  }
  const description = /description="([^"]*)"/.exec(text)?.[1];
  const status = /status="([^"]*)"/.exec(text)?.[1];
  const finished = /finished: (.*?)\. (Its|Their) report/.exec(text)?.[1];
  const label = description
    ? `Background agent ${status === "done" || !status ? "reported" : status === "cancelled" ? "was cancelled" : "stopped"} · ${description}`
    : `Background ${finished && finished.includes(",") ? "agents" : "agent"} finished${finished ? ` · ${finished.replace(/"/g, "")}` : ""}`;
  return (
    <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
      <span className="h-px flex-1 bg-border" />
      <AgentIcon background className="size-3.5" />
      <span className="max-w-[70%] truncate">{label}</span>
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}

export function UserMessage({ turn }: { turn: Turn }) {
  if (isBackgroundNote(turn.prompt)) return <BackgroundNote text={turn.prompt} />;
  return <UserPrompt turn={turn} />;
}

function TurnMeta({ turn }: { turn: Turn }) {
  const { meta } = turn;
  // Usage reports uncached input, cache reads and cache writes separately;
  // the prompt the model saw is their sum.
  const prompt = (meta.inputTokens ?? 0) + (meta.cacheRead ?? 0) + (meta.cacheWrite ?? 0);
  const total = prompt + (meta.outputTokens ?? 0);
  const parts = [
    meta.model,
    meta.durationMs !== undefined ? formatDuration(meta.durationMs) : undefined,
    total ? `${formatTokens(total)} tokens` : undefined,
    meta.cacheRead && prompt ? `${Math.round((meta.cacheRead / prompt) * 100)}% cached` : undefined,
    meta.cost ? formatCost(meta.cost) : undefined,
  ].filter(Boolean);
  if (parts.length === 0) return null;
  return <span className="font-mono text-xs text-muted-foreground tabular-nums">{parts.join(" · ")}</span>;
}

type Process = (ReasoningPart | ToolPart)[];
type Segment = { kind: "process"; key: string; parts: Process } | { kind: "text"; key: string; text: string; streaming: boolean };

/** Consecutive reasoning and tool parts form one group; text breaks it. */
function segments(parts: Part[]): Segment[] {
  const out: Segment[] = [];
  for (const part of parts) {
    if (part.kind === "text") {
      if (part.text) out.push({ kind: "text", key: part.key, text: part.text, streaming: part.streaming });
      continue;
    }
    const last = out.at(-1);
    if (last?.kind === "process") last.parts.push(part);
    else out.push({ kind: "process", key: part.key, parts: [part] });
  }
  return out;
}

function sentence(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;
}

/** "Running commands" while live; "Read files, ran commands and edited files" after. */
function groupTitle(parts: Process, live: boolean): string {
  const current = parts.at(-1)!;
  if (live) return current.kind === "reasoning" ? "Thinking" : activity[toolKind(current.name)].live;
  const counts = new Map<string, number>();
  for (const part of parts) {
    const label = part.kind === "reasoning" ? "thought" : activity[toolKind(part.name)].done;
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([label]) => label);
  const text = sentence(top);
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function ProcessRows({ parts, running }: { parts: Process; running: boolean }) {
  return (
    <Trace>
      {parts.map((part) =>
        part.kind === "reasoning" ? (
          <Reasoning key={part.key} text={part.text} streaming={part.streaming} startedAt={part.startedAt} endedAt={part.endedAt} />
        ) : (
          <Tool key={part.key} part={part} streaming={running} />
        ),
      )}
    </Trace>
  );
}

/** A process group: its rows, under a title once there is more than one. */
function ProcessGroup({ parts, running, live: turnLive }: { parts: Process; running: boolean; live: boolean }) {
  const [open, setOpen] = React.useState<boolean>();
  // A background agent keeps its group live after the turn ended.
  const background = parts.some((part) => part.kind === "tool" && part.details?.child?.status === "running");
  const live = turnLive || background;
  if (parts.length === 1) return <ProcessRows parts={parts} running={running} />;
  return (
    <TraceCollapsible open={open ?? live} onOpenChange={setOpen}>
      <TraceCollapsibleTrigger>
        <TraceLine status={live ? "running" : undefined}>
          <TraceTitle>{groupTitle(parts, live)}</TraceTitle>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent className="max-h-[min(400px,50vh)] overflow-y-auto">
        <ProcessRows parts={parts} running={running} />
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

/** "Working for 12s", ticking while the turn runs. */
function RunningStatus({ startedAt }: { startedAt: number }) {
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground" role="status" aria-live="polite">
      <Spinner />
      <span className="shimmer">Working for {seconds(now - startedAt)}</span>
    </div>
  );
}

export function AssistantMessage({ turn }: { turn: Turn }) {
  const [copied, setCopied] = React.useState(false);
  const running = turn.status === "running";
  const all = React.useMemo(() => segments(turn.parts), [turn.parts]);
  const hasProcess = all.some((segment) => segment.kind === "process");
  // A completed turn folds its process; failed or stopped turns stay open.
  const foldable = turn.status === "done" && hasProcess;
  const [expanded, setExpanded] = React.useState(false);
  // Folded, it keeps showing a background agent that is still running.
  const shown =
    foldable && !expanded
      ? all.filter(
          (segment) =>
            segment.kind === "text" ||
            segment.parts.some(
              (part) =>
                part.kind === "tool" &&
                // A running background agent, or a session card to act on.
                (part.details?.child?.status === "running" || (part.name === "start_session" && part.phase === "done")),
            ),
        )
      : all;
  const reply = turnReply(turn);
  // Files the agent sent stay in sight when the process folds: they are the
  // turn's deliverables.
  const sentFiles = foldable && !expanded
    ? turn.parts.flatMap((part) => {
        const sent = part.kind === "tool" && part.name === "send_file" ? part.details?.externalToolResult?.structuredContent : undefined;
        return sent && Array.isArray(sent.files) && sent.files.length ? [{ key: part.key, files: sent.files as SentFile[], caption: sent.caption as string | undefined }] : [];
      })
    : [];

  React.useEffect(() => {
    if (!copied) return;
    const timeout = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timeout);
  }, [copied]);

  return (
    <Message>
      <MessageContent className="gap-4">
        {foldable && (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="group/fold flex w-fit items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
            aria-expanded={expanded}
          >
            Completed in {seconds(turn.meta.durationMs ?? (turn.endedAt ?? turn.startedAt) - turn.startedAt)}
            <ChevronRightIcon className={cn("size-4 transition-transform", expanded && "rotate-90")} />
          </button>
        )}

        {sentFiles.map((sent) => (
          <div key={sent.key} className="@container -ml-7">
            <SentFiles files={sent.files} caption={sent.caption} />
          </div>
        ))}

        {shown.map((segment, index) =>
          segment.kind === "text" ? (
            <Markdown key={segment.key} streaming={segment.streaming}>
              {segment.text}
            </Markdown>
          ) : (
            <ProcessGroup
              key={segment.key}
              parts={segment.parts}
              running={running}
              live={running && index === all.length - 1}
            />
          ),
        )}

        {running && <RunningStatus startedAt={turn.startedAt} />}

        {turn.error && (
          <div className="flex items-start gap-2 text-sm text-destructive" data-selectable>
            <CircleAlertIcon className="mt-0.5 size-4 shrink-0" />
            <span>{turn.error}</span>
          </div>
        )}
        {turn.status === "aborted" && <p className="text-sm text-muted-foreground">Stopped.</p>}

        {!running && (
          <MessageFooter className="px-0">
            {reply && (
              <MessageAction
                label={copied ? "Copied" : "Copy"}
                onClick={() => {
                  void navigator.clipboard.writeText(reply);
                  setCopied(true);
                }}
              >
                {copied ? <CheckIcon /> : <CopyIcon />}
              </MessageAction>
            )}
            <TurnMeta turn={turn} />
          </MessageFooter>
        )}
      </MessageContent>
    </Message>
  );
}
