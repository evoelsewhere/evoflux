import * as React from "react";
import {
  FileIcon,
  FilePenIcon,
  FolderSearchIcon,
  GlobeIcon,
  MessagesSquareIcon,
  PlugIcon,
  BellIcon,
  BracesIcon,
  BrainIcon,
  ListChecksIcon,
  MessageCircleQuestionIcon,
  ScrollTextIcon,
  SearchIcon,
  ShapesIcon,
  TerminalIcon,
  WrenchIcon,
} from "lucide-react";
import { CodeBlock, CodeBlockContent, CodeBlockHeader, CodeBlockLine, CodeBlockTitle } from "@/components/ui/code-block";
import {
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceDescription,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from "@/components/ui/trace";
import { AgentIcon } from "@/components/icons/agent-icon";
import { BrowserIcon } from "@/components/icons/tool-icons";
import { partialField, type ToolPart } from "@/features/chat/transcript";
import { AgentRun, childRun } from "./agent-run";
import { SessionProposal } from "./session-proposal";
import { FileLink } from "./file-link";
import { openLink } from "@/features/shell/app-commands";
import { TodoList } from "@/features/chat/todo-bar";
import { SentFiles } from "./sent-files";
import { WidgetFrame } from "@/components/widget-frame";

// shadcn/ui AI Elements · Tool on Trace, following a call through DeepSeek
// Harness's phases: preparing (the model is still writing the arguments, so
// the row already names the command or file), running, done, error. Each tool
// has its own body — a terminal for shells, a diff for edits, the file for
// reads — with the arguments and output as the fallback.

type Kind =
  | "shell"
  | "read"
  | "write"
  | "edit"
  | "search"
  | "list"
  | "web"
  | "browser"
  | "agent"
  | "session"
  | "skill"
  | "memory"
  | "ask"
  | "todo"
  | "code"
  | "user"
  | "mcp"
  | "visual"
  | "other";

const kinds: Record<string, Kind> = {
  bash: "shell",
  powershell: "shell",
  read: "read",
  write: "write",
  edit: "edit",
  grep: "search",
  find: "search",
  ls: "list",
  web_fetch: "web",
  web_search: "web",
  agent: "agent",
  skill: "skill",
  start_session: "session",
  message_session: "session",
  list_sessions: "session",
  show_file: "read",
  document_preview: "read",
  terminal_run: "shell",
  terminal_read: "shell",
  browser_navigate: "browser",
  browser_tabs: "browser",
  browser_screenshot: "browser",
  browser_read_page: "browser",
  browser_find: "browser",
  browser_click: "browser",
  browser_type: "browser",
  browser_key: "browser",
  browser_form_input: "browser",
  browser_scroll: "browser",
  browser_eval: "browser",
  browser_console: "browser",
  browser_network: "browser",
  memory: "memory",
  ask_user: "ask",
  update_todos: "todo",
  lsp: "code",
  send_file: "user",
  notify: "user",
  mcp_search_tools: "mcp",
  mcp_call_tool: "mcp",
  show_widget: "visual",
  visualize_read_me: "visual",
};

const icons: Record<Kind, React.ComponentType<{ className?: string }>> = {
  shell: TerminalIcon,
  read: FileIcon,
  write: FilePenIcon,
  edit: FilePenIcon,
  search: SearchIcon,
  list: FolderSearchIcon,
  web: GlobeIcon,
  browser: BrowserIcon,
  agent: AgentIcon,
  session: MessagesSquareIcon,
  skill: ScrollTextIcon,
  memory: BrainIcon,
  ask: MessageCircleQuestionIcon,
  todo: ListChecksIcon,
  code: BracesIcon,
  user: BellIcon,
  mcp: PlugIcon,
  visual: ShapesIcon,
  other: WrenchIcon,
};

const verbs: Record<Kind, Record<ToolPart["phase"], string>> = {
  shell: { preparing: "Running", running: "Running", done: "Ran", error: "Failed to run" },
  read: { preparing: "Reading", running: "Reading", done: "Read", error: "Failed to read" },
  write: { preparing: "Writing", running: "Writing", done: "Wrote", error: "Failed to write" },
  edit: { preparing: "Editing", running: "Editing", done: "Edited", error: "Failed to edit" },
  search: { preparing: "Searching", running: "Searching", done: "Searched", error: "Failed to search" },
  list: { preparing: "Listing", running: "Listing", done: "Listed", error: "Failed to list" },
  web: { preparing: "Fetching", running: "Fetching", done: "Fetched", error: "Failed to fetch" },
  browser: { preparing: "Using the browser", running: "Using the browser", done: "Used the browser", error: "Browser step failed" },
  agent: { preparing: "Starting agent", running: "Agent", done: "Agent", error: "Agent failed" },
  session: { preparing: "Session", running: "Session", done: "Session", error: "Session failed" },
  skill: { preparing: "Loading skill", running: "Loading skill", done: "Skill", error: "Skill failed" },
  memory: { preparing: "Using memory", running: "Using memory", done: "Memory", error: "Memory failed" },
  ask: { preparing: "Asking you", running: "Waiting for your answer", done: "Asked you", error: "Question failed" },
  todo: { preparing: "Updating tasks", running: "Updating tasks", done: "Updated tasks", error: "Task update failed" },
  code: { preparing: "Checking code", running: "Checking code", done: "Checked code", error: "Code check failed" },
  user: { preparing: "Sending", running: "Sending", done: "Sent", error: "Could not send" },
  mcp: { preparing: "Calling", running: "Calling", done: "Called", error: "Failed" },
  visual: { preparing: "Drawing", running: "Drawing", done: "Drew", error: "Failed to draw" },
  other: { preparing: "Calling", running: "Calling", done: "Called", error: "Failed" },
};

/** What a category of tool does, for a group's title ("Ran commands, edited files"). */
export const activity: Record<Kind, { live: string; done: string }> = {
  shell: { live: "Running commands", done: "ran commands" },
  read: { live: "Reading files", done: "read files" },
  write: { live: "Writing files", done: "wrote files" },
  edit: { live: "Editing files", done: "edited files" },
  search: { live: "Searching", done: "searched" },
  list: { live: "Listing files", done: "listed files" },
  web: { live: "Browsing the web", done: "browsed the web" },
  browser: { live: "Using the browser", done: "used the browser" },
  agent: { live: "Running agents", done: "ran agents" },
  session: { live: "Working with sessions", done: "worked with sessions" },
  skill: { live: "Loading skills", done: "loaded skills" },
  memory: { live: "Using memory", done: "used memory" },
  ask: { live: "Asking you", done: "asked you" },
  todo: { live: "Updating tasks", done: "updated tasks" },
  code: { live: "Checking code", done: "checked code" },
  user: { live: "Reaching you", done: "reached you" },
  mcp: { live: "Using connectors", done: "used connectors" },
  visual: { live: "Drawing widgets", done: "drew widgets" },
  other: { live: "Using tools", done: "used tools" },
};

export const toolKind = (name: string): Kind => kinds[name] ?? (name.startsWith("mcp__") ? "mcp" : "other");

/** "Checked errors · src/main.rs", "Found references · add", … */
function codeLabel(part: ToolPart, phase: ToolPart["phase"]): string {
  const args = (part.args && typeof part.args === "object" ? part.args : {}) as Record<string, unknown>;
  const live = phase === "preparing" || phase === "running";
  const verbs: Record<string, [string, string]> = {
    diagnostics: ["Checking for errors", "Checked for errors"],
    definition: ["Finding the definition", "Found the definition"],
    type_definition: ["Finding the type", "Found the type"],
    implementation: ["Finding implementations", "Found implementations"],
    references: ["Finding references", "Found references"],
    hover: ["Reading type info", "Read type info"],
    symbols: ["Outlining", "Outlined"],
    workspace_symbols: ["Searching symbols", "Searched symbols"],
  };
  const [doing, did] = verbs[String(args.operation ?? "")] ?? ["Checking code", "Checked code"];
  const what =
    (typeof args.symbol === "string" && args.symbol) ||
    (typeof args.query === "string" && args.query) ||
    (typeof args.path === "string" && String(args.path).split(/[\\/]/).pop()) ||
    "";
  return `${phase === "error" ? "Code check failed" : live ? doing : did}${what ? ` · ${what}` : ""}`;
}

/** "Searched the web · query", "Read · docs.rs/serde". */
function webLabel(part: ToolPart, phase: ToolPart["phase"]): string {
  const args = (part.args && typeof part.args === "object" ? part.args : {}) as Record<string, unknown>;
  const live = phase === "preparing" || phase === "running";
  if (part.name === "web_search") {
    const query = typeof args.query === "string" ? args.query : partialField(part.argsText, "query");
    return `${phase === "error" ? "Search failed" : live ? "Searching the web" : "Searched the web"}${query ? ` · ${query}` : ""}`;
  }
  const raw = typeof args.url === "string" ? args.url : partialField(part.argsText, "url");
  let where = raw ?? "";
  try {
    const url = new URL(where.includes("://") ? where : `https://${where}`);
    where = `${url.hostname.replace(/^www\./, "")}${url.pathname === "/" ? "" : url.pathname}`;
  } catch {
    // Keep it as typed.
  }
  return `${phase === "error" ? "Could not read" : live ? "Reading" : "Read"}${where ? ` · ${where}` : ""}`;
}

/** Search results as links that open in the browser. */
function WebResults({ results }: { results: { title: string; url: string; snippet: string }[] }) {
  if (!results.length) return <p className="px-1 text-xs text-muted-foreground">No results.</p>;
  return (
    <ol className="flex flex-col gap-0.5">
      {results.map((r) => {
        let host = r.url;
        try {
          host = new URL(r.url).hostname.replace(/^www\./, "");
        } catch {
          // Keep the URL.
        }
        return (
          <li key={r.url}>
            <button
              type="button"
              title={r.url}
              onClick={() => openLink(r.url)}
              className="flex w-full min-w-0 flex-col rounded-md px-2 py-1 text-left transition-colors hover:bg-accent/60"
            >
              <span className="flex min-w-0 items-baseline gap-2">
                <span className="truncate text-[13px] text-link">{r.title || host}</span>
                <span className="shrink-0 text-[11px] text-muted-foreground">{host}</span>
              </span>
              {r.snippet && <span className="line-clamp-2 text-xs text-muted-foreground">{r.snippet}</span>}
            </button>
          </li>
        );
      })}
    </ol>
  );
}

/** The page's text without the `<web_page>` wrapper. */
function webPageBody(output: string | undefined): string {
  const text = output ?? "";
  const match = /^<web_page [^>]*>\n([\s\S]*?)\n<\/web_page>/.exec(text);
  return match ? match[1] + text.slice(match[0].length) : text;
}

/** "Saved memory · prefers-tabs", "Reading memory", … */
function memoryLabel(part: ToolPart, phase: ToolPart["phase"]): string {
  const args = (part.args && typeof part.args === "object" ? part.args : {}) as Record<string, unknown>;
  const name = typeof args.name === "string" ? args.name : partialField(part.argsText, "name");
  const live = phase === "preparing" || phase === "running";
  const updated = /^Updated /.test(part.output ?? "");
  const verb: Record<string, [string, string]> = {
    save: ["Saving memory", updated ? "Updated memory" : "Saved memory"],
    read: ["Reading memory", "Read memory"],
    list: ["Listing memories", "Listed memories"],
    delete: ["Forgetting", "Forgot"],
  };
  const [doing, did] = verb[String(args.action ?? "")] ?? ["Using memory", "Used memory"];
  return `${phase === "error" ? "Memory failed" : live ? doing : did}${name ? ` · ${name}` : ""}`;
}

/** The first loading message of a `show_widget` call, from its arguments or the JSON still streaming. */
function widgetLoading(part: ToolPart): string | undefined {
  const args = (part.args && typeof part.args === "object" ? part.args : {}) as Record<string, unknown>;
  if (Array.isArray(args.loading_messages) && typeof args.loading_messages[0] === "string") return args.loading_messages[0];
  const raw = /"loading_messages"\s*:\s*\[\s*"((?:[^"\\]|\\.)*)"/.exec(part.argsText)?.[1];
  if (raw === undefined) return undefined;
  try {
    return JSON.parse(`"${raw}"`) as string;
  } catch {
    return raw;
  }
}

/** "Widget · Revenue by region", "Read the widget guide · chart, diagram". */
function visualLabel(part: ToolPart, phase: ToolPart["phase"]): string {
  const args = (part.args && typeof part.args === "object" ? part.args : {}) as Record<string, unknown>;
  const live = phase === "preparing" || phase === "running";
  if (part.name === "visualize_read_me") {
    const modules = Array.isArray(args.modules) ? args.modules.map(String).join(", ") : "";
    return `${phase === "error" ? "Could not read the widget guide" : live ? "Reading the widget guide" : "Read the widget guide"}${
      modules ? ` · ${modules}` : ""
    }`;
  }
  const title = typeof args.title === "string" ? args.title : partialField(part.argsText, "title");
  return `${phase === "error" ? "Widget failed" : live ? "Building widget" : "Widget"}${title ? ` · ${title}` : ""}`;
}

/** A loaded skill's instructions without the `<skill …>` wrapper. */
function skillBody(output: string | undefined): string {
  const text = output ?? "";
  const match = /^<skill [^>]*>\n(?:References are relative to [^\n]*\n\n)?([\s\S]*?)\n<\/skill>/.exec(text);
  return match ? match[1] + text.slice(match[0].length) : text;
}

const FIELDS = ["command", "path", "file_path", "pattern", "query", "url"];
/** An agent call is named by its short description, a session by its title. */
const AGENT_FIELDS = ["description"];
const SESSION_FIELDS = ["title"];
const SKILL_FIELDS = ["name"];

/** The call's subject — from the parsed arguments, or from the JSON still streaming. */
function subject(part: ToolPart): string | undefined {
  const args = (part.args && typeof part.args === "object" ? part.args : {}) as Record<string, unknown>;
  const kind = toolKind(part.name);
  for (const field of kind === "agent" ? AGENT_FIELDS : kind === "session" ? SESSION_FIELDS : kind === "skill" ? SKILL_FIELDS : FIELDS) {
    const value = typeof args[field] === "string" ? (args[field] as string) : partialField(part.argsText, field);
    if (value) {
      const line = value.split("\n")[0];
      return toolKind(part.name) === "shell" ? line : line.replace(/\\/g, "/");
    }
  }
  return undefined;
}

/** One browser step in words: "Opened localhost:3000", "Clicked ref_4", "Took a screenshot". */
function browserLabel(part: ToolPart, phase: ToolPart["phase"]): string {
  const args = (part.args && typeof part.args === "object" ? part.args : {}) as Record<string, any>;
  const live = phase === "preparing" || phase === "running";
  const failed = phase === "error";
  const quote = (value: unknown, max = 40) => {
    const text = String(value ?? "");
    return `"${text.length > max ? `${text.slice(0, max)}…` : text}"`;
  };
  const target = args.ref ?? (typeof args.x === "number" ? `(${Math.round(args.x)}, ${Math.round(args.y)})` : "");
  const words: Record<string, [string, string]> = {
    browser_navigate: [
      ["back", "forward", "reload"].includes(args.url) ? `Going ${args.url}` : `Opening ${args.url ?? ""}`,
      ["back", "forward", "reload"].includes(args.url) ? `Went ${args.url}` : `Opened ${args.url ?? ""}`,
    ],
    browser_tabs: ["Checking browser tabs", "Checked browser tabs"],
    browser_screenshot: ["Taking a screenshot", "Took a screenshot"],
    browser_read_page: ["Reading the page", "Read the page"],
    browser_find: [`Finding ${quote(args.query)}`, `Found ${quote(args.query)}`],
    browser_click: [`Clicking ${target}`, `Clicked ${target}`],
    browser_type: [`Typing ${quote(args.text)}`, `Typed ${quote(args.text)}`],
    browser_key: [`Pressing ${args.key ?? ""}`, `Pressed ${args.key ?? ""}`],
    browser_form_input: [`Setting ${args.ref ?? "a field"}`, `Set ${args.ref ?? "a field"} to ${quote(args.value)}`],
    browser_scroll: [`Scrolling ${args.direction ?? ""}`, `Scrolled ${args.direction ?? ""}`],
    browser_eval: ["Running script in the page", "Ran script in the page"],
    browser_console: ["Reading the console", "Read the console"],
    browser_network: ["Reading network requests", "Read network requests"],
  };
  const [doing, done] = words[part.name] ?? ["Using the browser", "Used the browser"];
  return failed ? `Browser: ${done.charAt(0).toLowerCase()}${done.slice(1)} failed` : live ? doing : done;
}

/** The first line a read started at or an edit changed (1-based). */
function touchedLine(part: ToolPart): number | undefined {
  const args = (part.args && typeof part.args === "object" ? part.args : {}) as Record<string, unknown>;
  if (typeof args.offset === "number" && args.offset > 0) return args.offset;
  if (typeof args.line === "number" && args.line > 0) return args.line;
  const diff = typeof part.details?.diff === "string" ? part.details.diff : "";
  const changed = /^[+-]\s*(\d+)/m.exec(diff);
  return changed ? Number(changed[1]) : undefined;
}

interface DiffLine {
  variant: "default" | "added" | "removed";
  text: string;
}

/** The edit tool's `details.diff`: `+12 new`, `-12 old`, ` 12 same`, ` …`. */
function parseDiff(diff: string): { lines: DiffLine[]; added: number; removed: number } {
  let added = 0;
  let removed = 0;
  const lines = diff.split("\n").map((raw) => {
    const marker = raw[0];
    const text = raw.slice(1).replace(/^\s*\d+\s?/, "");
    if (marker === "+") {
      added++;
      return { variant: "added" as const, text };
    }
    if (marker === "-") {
      removed++;
      return { variant: "removed" as const, text };
    }
    return { variant: "default" as const, text: raw.trim() === "..." ? "…" : text };
  });
  return { lines, added, removed };
}

function Terminal({ command, output, failed }: { command?: string; output: string; failed: boolean }) {
  return (
    <CodeBlock size="sm" variant={failed ? "destructive" : "default"}>
      <CodeBlockContent wrap className="max-h-64" data-selectable>
        {command && (
          <CodeBlockLine>
            <span className="text-muted-foreground select-none">$ </span>
            {command}
          </CodeBlockLine>
        )}
        {(output || (failed ? "" : "(no output)")).split("\n").map((line, index) => (
          <CodeBlockLine key={index}>{line}</CodeBlockLine>
        ))}
      </CodeBlockContent>
    </CodeBlock>
  );
}

function Diff({ diff, path }: { diff: ReturnType<typeof parseDiff>; path?: string }) {
  return (
    <CodeBlock size="sm">
      {path && (
        <CodeBlockHeader>
          <CodeBlockTitle className="font-mono">{path}</CodeBlockTitle>
        </CodeBlockHeader>
      )}
      <CodeBlockContent className="max-h-72" data-selectable>
        {diff.lines.map((line, index) => (
          <CodeBlockLine key={index} variant={line.variant}>
            {line.text}
          </CodeBlockLine>
        ))}
      </CodeBlockContent>
    </CodeBlock>
  );
}

function Plain({ text, failed, title }: { text: string; failed: boolean; title?: string }) {
  return (
    <CodeBlock size="sm" variant={failed ? "destructive" : "default"}>
      {title && (
        <CodeBlockHeader>
          <CodeBlockTitle className="font-mono">{title}</CodeBlockTitle>
        </CodeBlockHeader>
      )}
      <CodeBlockContent wrap className="max-h-64" data-selectable>
        {text || "(no output)"}
      </CodeBlockContent>
    </CodeBlock>
  );
}

export function Tool({
  part,
  streaming,
  lineOnly,
}: {
  part: ToolPart;
  streaming: boolean;
  /** Just the row, never a body (a subagent's steps). */
  lineOnly?: boolean;
}) {
  const kind = toolKind(part.name);
  const Icon = icons[kind];
  const about = subject(part);
  // A call that never finished while the turn is over was interrupted.
  const phase: ToolPart["phase"] = !streaming && (part.phase === "running" || part.phase === "preparing") ? "error" : part.phase;
  // A background subagent runs on after its call returned.
  const child = kind === "agent" ? childRun(part) : undefined;
  const live = phase === "preparing" || phase === "running" || (phase === "done" && child?.status === "running");
  const failed = phase === "error";
  const sessionLabel: Record<string, string> = {
    start_session: phase === "done" ? "Session" : "Starting a session",
    message_session: phase === "done" ? "Messaged a session" : "Messaging a session",
    list_sessions: phase === "done" ? "Listed sessions" : "Listing sessions",
  };
  const label =
    kind === "session"
      ? `${phase === "error" ? "Session tool failed" : (sessionLabel[part.name] ?? part.name)}${
          about && part.name === "start_session" ? ` · ${about}` : ""
        }`
      : kind === "memory"
      ? memoryLabel(part, phase)
      : kind === "code"
      ? codeLabel(part, phase)
      : part.name === "notify"
      ? `${phase === "error" ? "Notification not sent" : phase === "done" ? "Notified you" : "Notifying you"}${
          (part.args as any)?.title ? ` · ${String((part.args as any).title)}` : ""
        }`
      : part.name === "send_file"
      ? `${phase === "error" ? "Could not send files" : phase === "done" ? "Sent you" : "Sending"}${(() => {
          const paths = (part.args as any)?.paths;
          const names = Array.isArray(paths) ? paths.map((p: unknown) => String(p).split(/[\\/]/).pop()) : [];
          return names.length ? ` · ${names.slice(0, 3).join(", ")}${names.length > 3 ? ` +${names.length - 3}` : ""}` : "";
        })()}`
      : kind === "ask"
      ? `${verbs.ask[phase]}${(() => {
          const qs = (part.args as any)?.questions;
          return Array.isArray(qs) && qs[0]?.question ? ` · ${String(qs[0].question)}` : "";
        })()}`
      : kind === "todo"
      ? `${verbs.todo[phase]}${(() => {
          const todos = (part.args as any)?.todos;
          if (!Array.isArray(todos)) return "";
          const done = todos.filter((t: any) => t?.status === "completed").length;
          return ` · ${done}/${todos.length} done`;
        })()}`
      : part.name === "mcp_search_tools"
      ? `${phase === "error" ? "Tool search failed" : phase === "done" ? "Searched connector tools" : "Searching connector tools"}${
          (part.args as any)?.query ? ` · ${String((part.args as any).query)}` : ""
        }`
      : kind === "mcp"
      ? (() => {
          // `mcp_call_tool` runs the tool named in its arguments.
          const name = part.name === "mcp_call_tool" ? String((part.args as any)?.name ?? "") : part.name;
          const [, server = "", ...rest] = name.split("__");
          return `${phase === "error" ? "Failed" : verbs.mcp[phase]} ${server} · ${rest.join("__")}`;
        })()
      : kind === "agent" || kind === "skill"
      ? `${verbs[kind][phase]}${about ? ` · ${about}` : ""}`
      : kind === "browser"
      ? browserLabel(part, phase)
      : kind === "web"
      ? webLabel(part, phase)
      : kind === "visual"
      ? visualLabel(part, phase)
      : `${verbs[kind][phase]} ${about ?? (kind === "other" ? part.name : "")}`.trim();
  // A file the call read or changed opens in the Files tool, at the line it touched.
  const fileTitle =
    about && (kind === "read" || kind === "write" || kind === "edit") ? (
      <>
        {part.name === "show_file" ? (phase === "done" ? "Showed" : verbs[kind][phase]) : verbs[kind][phase]}{" "}
        <FileLink path={about} line={touchedLine(part)} />
      </>
    ) : null;
  const diff = kind === "edit" && typeof part.details?.diff === "string" ? parseDiff(part.details.diff) : undefined;

  const line = (
    <TraceLine status={live ? "running" : failed ? "error" : undefined}>
      <TraceIcon>
        {kind === "agent" ? (
          <AgentIcon agentType={child?.agentType} background={child?.background} live={live} />
        ) : (
          <Icon />
        )}
      </TraceIcon>
      <TraceTitle className={kind === "shell" ? "font-mono text-[13px]" : undefined}>{fileTitle ?? label}</TraceTitle>
      {child?.background && <TraceDescription className="text-xs">background</TraceDescription>}
      {diff && (diff.added || diff.removed) ? (
        <TraceDescription className="font-mono text-xs">
          <span className="text-status-ok">+{diff.added}</span> <span className="text-destructive">-{diff.removed}</span>
        </TraceDescription>
      ) : null}
    </TraceLine>
  );

  // A widget shows under its line: a placeholder while the model writes it,
  // then the widget itself (also when the chat is replayed: it is rebuilt
  // from the call's arguments).
  if (part.name === "show_widget" && !lineOnly && phase !== "error") {
    const args = (part.args && typeof part.args === "object" ? part.args : {}) as Record<string, unknown>;
    const html = phase !== "preparing" && typeof args.widget_code === "string" ? args.widget_code : "";
    const loading = widgetLoading(part);
    return (
      <div className="flex flex-col gap-2">
        {line}
        <WidgetFrame
          html={html}
          title={typeof args.title === "string" && args.title ? args.title : "Widget"}
          height={typeof args.height === "number" ? args.height : undefined}
          loadingMessages={loading ? [loading] : undefined}
        />
      </div>
    );
  }
  // Not expandable while the model is still writing the call.
  if (phase === "preparing" || lineOnly) return line;
  // Files the agent sent stay open under the line: they are the result.
  const sent = part.name === "send_file" ? part.details?.externalToolResult?.structuredContent : undefined;
  if (sent && Array.isArray(sent.files) && sent.files.length) {
    return (
      <div className="@container flex flex-col">
        {line}
        <SentFiles files={sent.files} caption={sent.caption} />
      </div>
    );
  }
  // A proposed (or started) session is a card the person acts on.
  if (part.name === "start_session" && phase === "done") {
    return (
      <div className="flex flex-col gap-2">
        {line}
        <SessionProposal part={part} />
      </div>
    );
  }
  // A subagent shows its steps from the start, open while it runs.
  if (kind === "agent") {
    return (
      <TraceCollapsible defaultOpen={live || failed ? true : undefined}>
        <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <AgentRun part={{ ...part, phase }} live={live} />
        </TraceCollapsibleContent>
      </TraceCollapsible>
    );
  }
  if (phase === "running" && !part.output) return line;

  let body: React.ReactNode;
  if (kind === "browser")
    body = (
      <div className="flex flex-col gap-2">
        {part.images?.map((src, index) => (
          <img key={index} src={src} alt="Browser screenshot" className="max-h-96 w-auto self-start rounded-md ring-1 ring-border" />
        ))}
        {part.output && <Plain text={part.output} failed={failed} />}
      </div>
    );
  else if (kind === "todo" && !failed && Array.isArray((part.args as any)?.todos))
    body = <TodoList todos={(part.args as any).todos} live={false} />;
  else if (kind === "ask" && !failed)
    body = <Plain text={part.output} failed={false} title="Answers" />;
  else if (part.name === "web_search" && !failed && Array.isArray(part.details?.results))
    body = <WebResults results={part.details.results} />;
  else if (part.name === "web_fetch" && !failed)
    body = (
      <Plain
        text={webPageBody(part.output)}
        failed={false}
        title={part.details?.title ? String(part.details.title) : String(part.details?.finalUrl ?? "Page")}
      />
    );
  else if (kind === "shell") body = <Terminal command={subject(part)} output={part.output} failed={failed} />;
  else if (diff && !failed) body = <Diff diff={diff} path={about} />;
  else if (kind === "read" && !failed) body = <Plain text={part.output} failed={false} title={about} />;
  else if (kind === "skill" && !failed) body = <Plain text={skillBody(part.output)} failed={false} title="Instructions" />;
  else if (kind === "memory" && !failed && (part.args as any)?.action === "save")
    body = <Plain text={String((part.args as any)?.content ?? "")} failed={false} title={String((part.args as any)?.description ?? "Memory")} />;
  else if (kind === "other" || kind === "mcp")
    body = (
      <div className="flex flex-col gap-2">
        <Plain
          text={JSON.stringify((part.name === "mcp_call_tool" ? (part.args as any)?.arguments : part.args) ?? {}, null, 2)}
          failed={false}
          title="Input"
        />
        <Plain text={part.output} failed={failed} title={failed ? "Error" : "Output"} />
      </div>
    );
  else body = <Plain text={part.output} failed={failed} />;

  return (
    <TraceCollapsible defaultOpen={failed ? true : undefined}>
      <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
      <TraceCollapsibleContent>{body}</TraceCollapsibleContent>
    </TraceCollapsible>
  );
}
