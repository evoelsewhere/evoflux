import * as React from "react";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CheckIcon,
  ChevronRightIcon,
  FileDiffIcon,
  FilePenIcon,
  GitBranchIcon,
  GitCommitHorizontalIcon,
  RefreshCwIcon,
  SquareIcon,
  TargetIcon,
  XIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { resolvePath } from "@/features/files/fs";
import { git, type RepoStatus } from "@/lib/git";
import { formatCost, formatDuration, formatTokens } from "@/lib/format";
import { inTauri } from "@/lib/platform";
import { cn } from "@/lib/utils";
import { useElementWidth } from "@/hooks/use-element-width";
import type { FileChange } from "@/lib/worktrees";
import { useEngineStore } from "@/stores/engine-store";
import { openFile } from "@/stores/files-store";
import { useSessionStore } from "@/stores/session-store";
import { useUiStore } from "@/stores/ui-store";
import { useShallow } from "zustand/react/shallow";
import { AgentIcon } from "@/components/icons/agent-icon";
import { SideChatIcon } from "@/components/icons/tool-icons";
import { childRun } from "@/components/ai-elements/agent-run";
import { Spinner } from "@/components/ui/spinner";
import type { AgentReport, ToolPart, Turn } from "./transcript";
import { TodoList, type Todo } from "./todo-bar";

// The chat summary: a card over the thread's top right with where the
// workspace's repository stands (changes, branch), the task this chat works
// on with its progress, and the files the agent edited. Toggled from the
// toolbar; open by default.

const EDIT_TOOLS = new Set(["edit", "write"]);
/** The card's width and its gap to the edge, in px (`w-72`, `right-4`). */
const CARD_WIDTH = 288;
const CARD_GAP = 16;
/** The thread's column (`--chat-width`, 48rem) and its side padding. */
const CHAT_COLUMN = 768 + 48;

/** The repository of `cwd`, re-read when a turn ends and on demand. */
function useRepoStatus(cwd: string | undefined, enabled: boolean) {
  const busy = useEngineStore((s) => s.transcript.busy);
  const turns = useEngineStore((s) => s.transcript.turns.length);
  const [status, setStatus] = React.useState<RepoStatus | null>(null);
  const [loading, setLoading] = React.useState(false);
  const request = React.useRef(0);

  const refresh = React.useCallback(() => {
    if (!cwd || !inTauri) {
      setStatus(null);
      return;
    }
    const id = ++request.current;
    setLoading(true);
    git
      .status(cwd)
      .then((next) => id === request.current && setStatus(next))
      .catch(() => id === request.current && setStatus(null))
      .finally(() => id === request.current && setLoading(false));
  }, [cwd]);

  // On open, on another folder, and each time the agent stops working.
  React.useEffect(() => {
    if (enabled && !busy) refresh();
  }, [enabled, busy, turns, refresh]);

  // Edits made outside the app show up when the window comes back.
  React.useEffect(() => {
    if (!enabled) return;
    const onFocus = () => refresh();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [enabled, refresh]);

  return { status, loading, refresh };
}

interface ChatSummary {
  todos: Todo[] | null;
  /** The turn that wrote the task list is still running. */
  live: boolean;
  turns: number;
  durationMs: number;
  tokens: number;
  cost: number;
  /** Files the agent wrote or edited, most recent first, with how often. */
  edited: { path: string; count: number }[];
  /** Subagents this chat started (`agent` calls), oldest first. */
  agents: SubagentEntry[];
  state: "idle" | "running" | "done" | "error" | "aborted";
}

interface SubagentEntry {
  key: string;
  /** Set for a background agent, which can be stopped while it runs. */
  agentId?: string;
  description: string;
  agentType?: string;
  background: boolean;
  status: "running" | "done" | "error" | "cancelled";
  toolUses: number;
  tokens: number;
  startedAt?: number;
  endedAt?: number;
}

/** One `agent` call as a summary row, from its streamed `details.child`. */
function subagentOf(part: ToolPart): SubagentEntry {
  const child = childRun(part);
  const args = (part.args ?? {}) as Record<string, unknown>;
  const phaseStatus = part.phase === "error" ? "error" : part.phase === "done" ? "done" : "running";
  return {
    key: part.callId,
    agentId: child?.agentId,
    description: child?.description || (typeof args.description === "string" ? args.description : "") || "Subagent",
    agentType: child?.agentType ?? (typeof args.subagent_type === "string" ? args.subagent_type : undefined),
    background: Boolean(child?.background ?? args.background),
    // A background agent's call ends at once; its own status says how it is doing.
    status: child?.status ?? phaseStatus,
    toolUses: child?.toolUses ?? child?.tools?.length ?? 0,
    tokens: child?.usage?.totalTokens ?? 0,
    startedAt: child?.startedAt ?? part.startedAt,
    endedAt: child?.endedAt ?? (child?.status && child.status !== "running" ? part.endedAt : undefined) ?? undefined,
  };
}

/**
 * How background agents ended: the reports the chat received (kept on the
 * transcript, `agentReports`), and the app's wake listing the agents that
 * finished. The `agent` call keeps the snapshot from when it started, and after
 * a restart nothing live updates it.
 */
function agentReports(turns: Turn[], received: Record<string, AgentReport> | undefined) {
  const reports: Record<string, AgentReport> = {};
  for (const turn of turns) {
    const finished = /<background-agents-done>\s*[^:]*finished: (.*?)\. (?:Its|Their) report/.exec(turn.prompt)?.[1];
    for (const match of finished?.matchAll(/"([^"]*)"/g) ?? []) {
      reports[`description:${match[1]}`] ??= { status: "done", at: turn.startedAt };
    }
  }
  return { ...reports, ...received };
}

/** A running background agent whose report already came in has ended. */
function settle(agent: SubagentEntry, reports: Record<string, AgentReport>): SubagentEntry {
  if (agent.status !== "running" || !agent.background) return agent;
  const report =
    (agent.agentId ? reports[`id:${agent.agentId}`] : undefined) ??
    reports[`description:${agent.description.replace(/"/g, "'")}`];
  return report ? { ...agent, status: report.status, endedAt: agent.endedAt ?? report.at } : agent;
}

const turnTokens = (meta: Turn["meta"]) =>
  (meta.inputTokens ?? 0) + (meta.outputTokens ?? 0) + (meta.cacheRead ?? 0) + (meta.cacheWrite ?? 0);

/** Everything the summary shows about the chat itself, from its transcript. */
function useChatSummary(): ChatSummary {
  const turns = useEngineStore((s) => s.transcript.turns);
  const received = useEngineStore((s) => s.transcript.agentReports);
  return React.useMemo(() => {
    let todos: Todo[] | null = null;
    let live = false;
    let durationMs = 0;
    let tokens = 0;
    let cost = 0;
    const edited = new Map<string, number>();
    const agents: SubagentEntry[] = [];
    const reports = agentReports(turns, received);
    for (let t = turns.length - 1; t >= 0; t--) {
      const turn = turns[t];
      durationMs += turn.meta.durationMs ?? (turn.endedAt ?? Date.now()) - turn.startedAt;
      tokens += turnTokens(turn.meta);
      cost += turn.meta.cost ?? 0;
      for (let p = turn.parts.length - 1; p >= 0; p--) {
        const part = turn.parts[p];
        if (part.kind !== "tool") continue;
        if (part.name === "agent" && part.phase !== "preparing") agents.push(settle(subagentOf(part), reports));
        if (!todos && part.name === "update_todos") {
          const list = (part.details?.todos ?? (part.args as any)?.todos) as Todo[] | undefined;
          if (Array.isArray(list)) {
            todos = list;
            live = turn.status === "running";
          }
        }
        if (EDIT_TOOLS.has(part.name) && part.phase !== "error") {
          const args = (part.args ?? {}) as Record<string, unknown>;
          const path = (args.path ?? args.file_path) as string | undefined;
          if (typeof path === "string" && path) {
            const key = path.replace(/\\/g, "/");
            edited.set(key, (edited.get(key) ?? 0) + 1);
          }
        }
      }
    }
    const last = turns.at(-1);
    return {
      todos,
      live,
      turns: turns.length,
      durationMs,
      tokens,
      cost,
      edited: [...edited].map(([path, count]) => ({ path, count })),
      agents: agents.reverse(),
      state: last ? last.status : "idle",
    };
  }, [turns, received]);
}

/** `src/app/main.tsx` → `main.tsx` with `src/app` beside it. */
function splitPath(path: string) {
  const at = path.lastIndexOf("/");
  return at < 0 ? { name: path, dir: "" } : { name: path.slice(at + 1), dir: path.slice(0, at) };
}

function LineCounts({
  added,
  removed,
  className,
}: {
  added: number | null;
  removed: number | null;
  className?: string;
}) {
  if (added === null && removed === null) return <span className={cn("text-muted-foreground", className)}>binary</span>;
  return (
    <span className={cn("font-mono tabular-nums", className)}>
      {added ? <span className="text-status-ok">+{added}</span> : null}
      {added && removed ? " " : null}
      {removed ? <span className="text-status-error">−{removed}</span> : null}
    </span>
  );
}

const STATUS_LETTER: Record<FileChange["status"], { letter: string; className: string }> = {
  added: { letter: "A", className: "text-status-ok" },
  modified: { letter: "M", className: "text-status-warn" },
  deleted: { letter: "D", className: "text-status-error" },
};

function FileRow({ path, onOpen, children }: { path: string; onOpen?: () => void; children?: React.ReactNode }) {
  const { name, dir } = splitPath(path);
  return (
    <li>
      <button
        type="button"
        disabled={!onOpen}
        onClick={onOpen}
        title={path}
        className="flex w-full min-w-0 items-center gap-2 rounded-md px-1.5 py-0.5 text-left text-xs hover:bg-accent disabled:hover:bg-transparent"
      >
        <span className="min-w-0 flex-1 truncate">
          <span className="text-foreground">{name}</span>
          {dir && <span className="ml-1.5 text-muted-foreground">{dir}</span>}
        </span>
        {children}
      </button>
    </li>
  );
}

function Section({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-1.5 border-t px-3 py-2.5 first:border-t-0">
      <div className="flex h-5 items-center gap-2">
        <h3 className="flex-1 text-xs font-medium text-muted-foreground">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

/** A row that opens onto a list: an icon, a label, figures at the right. */
function ExpandRow({
  icon,
  label,
  figures,
  count,
  children,
}: {
  icon: React.ReactNode;
  label: React.ReactNode;
  figures?: React.ReactNode;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <Collapsible>
      <CollapsibleTrigger
        disabled={count === 0}
        className="group flex w-full items-center gap-2 rounded-md py-0.5 text-left text-[13px] disabled:cursor-default"
      >
        <span className="flex size-4 shrink-0 items-center justify-center text-muted-foreground [&_svg]:size-4">
          {icon}
        </span>
        <span className="min-w-0 flex-1 truncate">{label}</span>
        {figures}
        {count > 0 && (
          <ChevronRightIcon className="size-3.5 shrink-0 text-muted-foreground transition-transform group-data-[panel-open]:rotate-90" />
        )}
      </CollapsibleTrigger>
      <CollapsibleContent className="h-(--collapsible-panel-height) overflow-hidden transition-[height] duration-200 data-ending-style:h-0 data-starting-style:h-0">
        <ul className="scrollbar-slim mt-1 ml-2 max-h-48 overflow-x-hidden overflow-y-auto border-l pl-1.5">
          {children}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

function GitSection({ repo }: { repo: ReturnType<typeof useRepoStatus> }) {
  const { status, loading, refresh } = repo;
  if (!status) return null;
  const open = (path: string) => void openFile(resolvePath(status.root, path));
  const where = status.branch ?? (status.head ? `Detached at ${status.head}` : "No branch");
  return (
    <Section
      title="Git"
      aside={
        <Button
          variant="ghost"
          size="icon-xs"
          className="size-5 text-muted-foreground"
          aria-label="Refresh"
          title="Refresh"
          onClick={refresh}
        >
          <RefreshCwIcon className={cn("size-3", loading && "animate-spin")} />
        </Button>
      }
    >
      <ExpandRow
        icon={<FileDiffIcon />}
        label={status.files.length ? `Changes` : "No changes"}
        count={status.files.length}
        figures={
          status.files.length > 0 && (
            <span className="flex items-center gap-2 text-xs">
              <span className="text-muted-foreground tabular-nums">{status.files.length} files</span>
              <LineCounts added={status.added} removed={status.removed} />
            </span>
          )
        }
      >
        {status.files.map((file) => (
          <FileRow
            key={file.path}
            path={file.path}
            onOpen={file.status === "deleted" ? undefined : () => open(file.path)}
          >
            <LineCounts added={file.added} removed={file.removed} className="text-[11px]" />
            <span className={cn("w-3 text-center font-mono text-[11px]", STATUS_LETTER[file.status].className)}>
              {STATUS_LETTER[file.status].letter}
            </span>
          </FileRow>
        ))}
      </ExpandRow>
      <div
        className="flex items-center gap-2 py-0.5 text-[13px]"
        title={status.upstream ? `Tracks ${status.upstream}` : "No upstream branch"}
      >
        <GitBranchIcon className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate">{where}</span>
        {(status.ahead > 0 || status.behind > 0) && (
          <span className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground tabular-nums">
            {status.ahead > 0 && (
              <span className="flex items-center" title={`${status.ahead} commits to push`}>
                <ArrowUpIcon className="size-3" />
                {status.ahead}
              </span>
            )}
            {status.behind > 0 && (
              <span className="flex items-center" title={`${status.behind} commits to pull`}>
                <ArrowDownIcon className="size-3" />
                {status.behind}
              </span>
            )}
          </span>
        )}
      </div>
      {status.head && (
        <div className="flex items-center gap-2 py-0.5 text-[13px] text-muted-foreground">
          <GitCommitHorizontalIcon className="size-4 shrink-0" />
          <span className="font-mono text-xs">{status.head}</span>
          {!status.upstream && status.branch && <span className="text-xs">· not published</span>}
        </div>
      )}
    </Section>
  );
}

/** Working, complete (every task done), in progress, stopped or failed. */
function taskState(summary: ChatSummary, done: number, total: number): { label: string; active: boolean } {
  if (summary.state === "running") return { label: "Working", active: true };
  if (summary.state === "error") return { label: "Failed", active: false };
  if (total > 0)
    return {
      label: done === total ? "Complete" : "In progress",
      active: false,
    };
  if (summary.state === "aborted") return { label: "Stopped", active: false };
  return {
    label: summary.state === "done" ? "Complete" : "Not started",
    active: false,
  };
}

function TaskSection({ summary, title }: { summary: ChatSummary; title: string }) {
  const done = summary.todos?.filter((t) => t.status === "completed").length ?? 0;
  const total = summary.todos?.length ?? 0;
  const state = taskState(summary, done, total);
  const meta = [
    total > 0 ? `${done}/${total}` : null,
    summary.durationMs > 0 ? formatDuration(summary.durationMs) : null,
    summary.tokens > 0 ? `${formatTokens(summary.tokens)} tokens` : null,
  ].filter(Boolean);
  return (
    <Section
      title="Task"
      aside={
        <span className={cn("text-xs", state.active ? "text-brand" : "text-muted-foreground")}>{state.label}</span>
      }
    >
      <div className="flex items-start gap-2">
        <TargetIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <p className="line-clamp-2 text-[13px] leading-5">{title}</p>
          {meta.length > 0 && <p className="text-xs text-muted-foreground tabular-nums">{meta.join(" · ")}</p>}
        </div>
      </div>
      {total > 0 && (
        <span className="mt-0.5 h-1 w-full overflow-hidden rounded-full bg-muted">
          <span
            className="block h-full rounded-full bg-brand transition-all"
            style={{ width: `${(done / total) * 100}%` }}
          />
        </span>
      )}
    </Section>
  );
}

/** Re-render every second while `active`, for running times. */
function useTick(active: boolean) {
  const [, setTick] = React.useState(0);
  React.useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
}

const AGENT_STATUS: Record<SubagentEntry["status"], string> = {
  running: "Running",
  done: "Done",
  error: "Failed",
  cancelled: "Cancelled",
};

function StatusMark({ status }: { status: SubagentEntry["status"] }) {
  if (status === "running") return <Spinner className="size-3.5 shrink-0 text-brand" />;
  if (status === "done") return <CheckIcon className="size-3.5 shrink-0 text-status-ok" />;
  return <XIcon className="size-3.5 shrink-0 text-status-error" />;
}

function SubagentRow({ agent, chat }: { agent: SubagentEntry; chat: string | null }) {
  const cancel = useEngineStore((s) => s.cancelBackgroundAgent);
  const live = agent.status === "running";
  const elapsed = agent.startedAt ? (agent.endedAt ?? Date.now()) - agent.startedAt : 0;
  const facts = [
    agent.background ? "background" : null,
    agent.agentType && !["general", "general-purpose"].includes(agent.agentType) ? agent.agentType : null,
    agent.toolUses ? `${agent.toolUses} ${agent.toolUses === 1 ? "tool" : "tools"}` : null,
    agent.tokens ? `${formatTokens(agent.tokens)} tokens` : null,
    elapsed > 0 ? formatDuration(elapsed) : null,
  ].filter(Boolean);
  const stoppable = live && agent.background && agent.agentId && chat;
  return (
    <li
      className="group/agent flex items-start gap-2 py-1"
      title={`${agent.description} · ${AGENT_STATUS[agent.status]}`}
    >
      <AgentIcon
        agentType={agent.agentType}
        background={agent.background}
        live={live}
        className={cn("mt-0.5 size-4", live ? "text-brand" : "text-muted-foreground")}
      />
      <div className="min-w-0 flex-1">
        <p
          className={cn("truncate text-[13px] leading-5", !live && agent.status !== "done" && "text-muted-foreground")}
        >
          {agent.description}
        </p>
        {facts.length > 0 && (
          <p className="truncate text-[11px] text-muted-foreground tabular-nums">{facts.join(" · ")}</p>
        )}
      </div>
      {stoppable ? (
        <span className="relative mt-0.5 flex size-4 shrink-0 items-center justify-center">
          <span className="group-hover/agent:invisible">
            <StatusMark status={agent.status} />
          </span>
          <button
            type="button"
            aria-label={`Stop ${agent.description}`}
            title="Stop agent"
            onClick={() => void cancel(chat!, agent.agentId!)}
            className="invisible absolute inset-0 flex items-center justify-center rounded text-muted-foreground group-hover/agent:visible hover:text-foreground"
          >
            <SquareIcon className="size-3" />
          </button>
        </span>
      ) : (
        <span className="mt-0.5 flex size-4 shrink-0 items-center justify-center">
          <StatusMark status={agent.status} />
        </span>
      )}
    </li>
  );
}

/** Sessions this chat's agent started, one click away. */
function ChildSessionRow({ id, title }: { id: string; title: string }) {
  const select = useEngineStore((s) => s.selectSession);
  const running = useEngineStore((s) => Boolean(s.busyElsewhere[id]));
  return (
    <li>
      <button
        type="button"
        onClick={() => void select(id)}
        title={`Open ${title}`}
        className="flex w-full items-center gap-2 rounded-md py-1 text-left text-[13px] hover:text-foreground"
      >
        <SideChatIcon className={cn("size-4 shrink-0", running ? "text-brand" : "text-muted-foreground")} />
        <span className="min-w-0 flex-1 truncate">{title}</span>
        <span className="text-[11px] text-muted-foreground">{running ? "Running" : "Session"}</span>
      </button>
    </li>
  );
}

/** Subagents (foreground and background) and nested sessions this chat started. */
function AgentsSection({ agents }: { agents: SubagentEntry[] }) {
  const chat = useEngineStore((s) => s.activeId);
  const sessions = useSessionStore(
    useShallow((s) => s.sessions.filter((x) => x.parentChatId && x.parentChatId === s.currentId)),
  );
  const running = agents.filter((a) => a.status === "running").length;
  useTick(running > 0);
  if (agents.length === 0 && sessions.length === 0) return null;
  return (
    <Section
      title="Agents"
      aside={
        <span className={cn("text-xs tabular-nums", running ? "text-brand" : "text-muted-foreground")}>
          {running ? `${running} running` : `${agents.length + sessions.length}`}
        </span>
      }
    >
      <ul className="scrollbar-slim -my-1 max-h-64 overflow-x-hidden overflow-y-auto">
        {agents.map((agent) => (
          <SubagentRow key={agent.key} agent={agent} chat={chat} />
        ))}
        {sessions.map((session) => (
          <ChildSessionRow key={session.id} id={session.id} title={session.title} />
        ))}
      </ul>
    </Section>
  );
}

function EditedSection({ edited, cwd }: { edited: ChatSummary["edited"]; cwd?: string }) {
  if (edited.length === 0) return null;
  return (
    <Section title="Edited in this chat">
      <ExpandRow
        icon={<FilePenIcon />}
        label={`${edited.length} ${edited.length === 1 ? "file" : "files"}`}
        count={edited.length}
      >
        {edited.map((file) => (
          <FileRow
            key={file.path}
            path={file.path}
            onOpen={() => void openFile(cwd ? resolvePath(cwd, file.path) : file.path)}
          >
            {file.count > 1 && <span className="font-mono text-[11px] text-muted-foreground">×{file.count}</span>}
          </FileRow>
        ))}
      </ExpandRow>
    </Section>
  );
}

/** Hide the overlay on Escape or a press outside it (the toolbar toggle excepted). */
function useDismiss(ref: React.RefObject<HTMLElement | null>, active: boolean, dismiss: () => void) {
  React.useEffect(() => {
    if (!active) return;
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Element | null;
      if (!target || ref.current?.contains(target) || target.closest("[data-summary-toggle]")) return;
      dismiss();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") dismiss();
    };
    document.addEventListener("pointerdown", onPointer, true);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer, true);
      document.removeEventListener("keydown", onKey);
    };
  }, [ref, active, dismiss]);
}

/**
 * The summary card over the thread's top right. Pinned (toolbar → Summary,
 * open by default) where it fits beside the messages; in a narrower chat it
 * opens from the toolbar as an overlay and closes on a click outside. Nothing
 * shows while there is nothing to sum up: a fresh chat outside a repository.
 */
export function SummaryCard() {
  const [measure, width] = useElementWidth<HTMLDivElement>();
  const fits = width === 0 || (width - CHAT_COLUMN) / 2 >= CARD_WIDTH + CARD_GAP;
  const setFits = useUiStore((s) => s.setSummaryFits);
  const setPeek = useUiStore((s) => s.setSummaryPeek);
  const shown = useUiStore((s) => (fits ? s.summaryOpen : s.summaryPeek));
  const toggle = useUiStore((s) => s.toggleSummary);
  const cwd = useEngineStore((s) => s.cwd);
  const model = useEngineStore((s) => s.state.model ?? s.state.modelId);
  const context = useEngineStore((s) => s.state.context);
  const title = useSessionStore((s) => s.sessions.find((x) => x.id === s.currentId)?.title) ?? "New chat";
  const repo = useRepoStatus(cwd, shown);
  const summary = useChatSummary();
  const card = React.useRef<HTMLElement | null>(null);
  const dismiss = React.useCallback(() => setPeek(false), [setPeek]);

  React.useEffect(() => setFits(fits), [fits, setFits]);
  useDismiss(card, shown && !fits, dismiss);
  const empty = !repo.status && summary.turns === 0;

  const footer = [
    model,
    `${summary.turns} ${summary.turns === 1 ? "turn" : "turns"}`,
    summary.cost > 0 ? formatCost(summary.cost) : null,
    context?.window ? `${Math.round((context.tokens / context.window) * 100)}% context` : null,
  ].filter(Boolean);

  return (
    // Spans the thread to measure it; only the card takes clicks.
    <div ref={measure} className="pointer-events-none absolute inset-0 z-20">
      {shown && !empty && (
        <aside
          ref={card}
          aria-label="Summary"
          className={cn(
            "group/summary pointer-events-auto absolute top-2 right-4 flex max-h-[calc(100%-1rem)] w-72 flex-col overflow-hidden rounded-xl border bg-popover text-popover-foreground",
            fits ? "shadow-sm" : "shadow-xl",
          )}
        >
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label="Hide summary"
            title="Hide summary"
            onClick={() => toggle(false)}
            className="absolute top-2.5 right-2 z-10 size-5 text-muted-foreground opacity-0 transition-opacity group-hover/summary:opacity-100 focus-visible:opacity-100"
          >
            <XIcon className="size-3" />
          </Button>
          <div className="scrollbar-slim min-h-0 overflow-x-hidden overflow-y-auto [&>section:first-child>div:first-child]:pr-6">
            <GitSection repo={repo} />
            {summary.turns > 0 && <TaskSection summary={summary} title={title} />}
            {summary.todos && summary.todos.length > 0 && (
              <Section title="Progress">
                <div className="scrollbar-slim max-h-64 overflow-x-hidden overflow-y-auto pl-0.5">
                  <TodoList todos={summary.todos} live={summary.live} />
                </div>
              </Section>
            )}
            <AgentsSection agents={summary.agents} />
            <EditedSection edited={summary.edited} cwd={cwd} />
            {summary.turns > 0 && (
              <p className="border-t px-3 py-2 text-[11px] text-muted-foreground">{footer.join(" · ")}</p>
            )}
          </div>
        </aside>
      )}
    </div>
  );
}
