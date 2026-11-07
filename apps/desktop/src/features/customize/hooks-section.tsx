import * as React from "react";
import { CircleAlertIcon, FileCogIcon, RefreshCwIcon, WebhookIcon } from "lucide-react";
import { openPath } from "@tauri-apps/plugin-opener";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";
import { Badge, IconAction } from "./customize-parts";

// Customize → Hooks: commands (or web requests) that run on agent events,
// from `hooks` in your settings and a trusted project's .evo/settings.json
// (crates/evo-hooks, crates/evo-engine/src/hooks.rs). Read-only here: hooks
// are edited in those files; this shows what is in effect and what ran.

interface Handler {
  type: "command" | "http";
  command?: string;
  args?: string[];
  url?: string;
  timeout?: number;
}

interface HookEntry {
  event: string;
  matcher?: string | null;
  handler: Handler;
  source: string;
  file: string;
}

interface RunRecord {
  event: string;
  hook: string;
  source: string;
  target?: string | null;
  result: "ok" | "blocked" | "error" | "timeout";
  exit?: number | null;
  ms: number;
  detail?: string | null;
  at: number;
}

interface HooksState {
  entries: HookEntry[];
  disabled: boolean;
  problems: string[];
  recent: RunRecord[];
  events: string[];
  userSettings?: string | null;
  projectSettings?: string | null;
}

const EXAMPLE = `{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "bash|powershell",
        "hooks": [{ "type": "command", "command": "node scripts/check-command.js", "timeout": 30 }]
      }
    ],
    "PostToolUse": [
      { "matcher": "edit|write", "hooks": [{ "type": "command", "command": "bun run format" }] }
    ]
  }
}`;

const eventHelp: Record<string, string> = {
  SessionStart: "When a chat's engine starts. Output becomes context for the first message.",
  UserPromptSubmit: "Before your message runs. Can block it or add context (exit 2 or JSON).",
  PreToolUse: "Before a tool runs. Can block it, ask you first, allow it, or change its input.",
  PostToolUse: "After a tool ran. Feedback and context are added to its result.",
  PostToolUseFailure: "After a tool failed.",
  Stop: "When a run ends.",
  SessionEnd: "When the chat's engine closes.",
};

const resultTone: Record<RunRecord["result"], string> = {
  ok: "text-status-ok",
  blocked: "text-amber-600 dark:text-amber-400",
  error: "text-destructive",
  timeout: "text-destructive",
};

function summary(handler: Handler) {
  if (handler.type === "http") return `POST ${handler.url}`;
  return [handler.command, ...(handler.args ?? [])].join(" ");
}

export function HooksSection({ query }: { query: string }) {
  const ready = useEngineStore((s) => (s.activeId ? s.runtimes[s.activeId]?.status === "ready" : false));
  const [state, setState] = React.useState<HooksState | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      setState(await useEngineStore.getState().request<HooksState>("list_hooks"));
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    if (ready) void load();
  }, [ready, load]);

  if (!state) {
    return (
      <div className="flex flex-1 items-center justify-center">
        {error ? <p className="text-[13px] text-muted-foreground">Could not read hooks: {error}</p> : <Spinner className="size-4 text-muted-foreground" />}
      </div>
    );
  }

  const q = query.trim().toLowerCase();
  const entries = state.entries.filter(
    (e) => !q || e.event.toLowerCase().includes(q) || summary(e.handler).toLowerCase().includes(q) || (e.matcher ?? "").toLowerCase().includes(q),
  );
  const byEvent = state.events
    .map((event) => ({ event, entries: entries.filter((e) => e.event === event) }))
    .concat(
      [...new Set(entries.map((e) => e.event))]
        .filter((event) => !state.events.includes(event))
        .map((event) => ({ event, entries: entries.filter((e) => e.event === event) })),
    );

  return (
    <div className="scrollbar-slim min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-4xl flex-col gap-6 px-6 py-5">
        <header className="flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand/12 text-brand">
            <WebhookIcon className="size-5" />
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <h2 className="text-base font-semibold">Hooks</h2>
            <p className="text-[13px] text-muted-foreground">
              Commands or web requests that run on agent events and can steer them: check a command before it runs, format
              files after an edit, add context to your messages. They run with your permissions.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <IconAction label="Read the settings again" onClick={() => void load()}>
              <RefreshCwIcon className={cn(loading && "animate-spin")} />
            </IconAction>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              {state.disabled ? "All off" : "On"}
              <Switch
                aria-label="Use hooks"
                checked={!state.disabled}
                onCheckedChange={async (on) => {
                  const next = await useEngineStore.getState().request<HooksState>("set_hooks_disabled", { disabled: !on });
                  setState(next);
                }}
              />
            </label>
          </div>
        </header>

        {state.problems.length > 0 && (
          <div className="flex gap-2.5 rounded-xl border border-amber-500/30 bg-amber-500/8 px-3.5 py-3 text-[13px]">
            <CircleAlertIcon className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
            <div className="flex min-w-0 flex-col gap-1">
              <p className="font-medium">Some hooks were skipped</p>
              {state.problems.map((p) => (
                <p key={p} className="font-mono text-xs break-words text-muted-foreground">
                  {p}
                </p>
              ))}
            </div>
          </div>
        )}

        <section className={cn("flex flex-col gap-3", state.disabled && "opacity-55")}>
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-medium text-muted-foreground">
              {state.entries.length} {state.entries.length === 1 ? "hook" : "hooks"}
            </h3>
            <div className="flex items-center gap-1">
              {state.userSettings && (
                <Button size="xs" variant="outline" onClick={() => void openPath(state.userSettings!).catch(() => undefined)}>
                  <FileCogIcon />
                  Your settings
                </Button>
              )}
              {state.projectSettings && (
                <Button size="xs" variant="outline" onClick={() => void openPath(state.projectSettings!).catch(() => undefined)}>
                  <FileCogIcon />
                  Project settings
                </Button>
              )}
            </div>
          </div>
          <div className="divide-y divide-border/60 overflow-hidden rounded-xl border border-border/70">
            {byEvent.map(({ event, entries }) => (
              <div key={event} className="flex flex-col gap-1.5 px-3.5 py-2.5">
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-xs font-medium">{event}</span>
                  <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">{eventHelp[event] ?? ""}</span>
                  <span className="text-[11px] text-muted-foreground tabular-nums">{entries.length || ""}</span>
                </div>
                {entries.map((entry, index) => (
                  <div key={index} className="flex min-w-0 items-center gap-2 pl-3 text-xs">
                    <Badge>{entry.matcher ? entry.matcher : "every time"}</Badge>
                    <code className="min-w-0 flex-1 truncate font-mono" title={summary(entry.handler)}>
                      {summary(entry.handler)}
                    </code>
                    <Badge tone={entry.source === "project" ? "brand" : undefined}>
                      {entry.source === "project" ? "Project" : entry.source.startsWith("plugin:") ? `Plugin · ${entry.source.slice(7)}` : "Yours"}
                    </Badge>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="text-xs font-medium text-muted-foreground">Recent runs in this chat</h3>
          {state.recent.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border/70 px-4 py-5 text-center text-xs text-muted-foreground">
              No hook has run yet.
            </p>
          ) : (
            <div className="overflow-hidden rounded-xl border border-border/70">
              <table className="w-full table-fixed text-xs">
                <thead className="bg-muted/40 text-left text-[11px] text-muted-foreground dark:bg-accent/30">
                  <tr>
                    <th className="w-24 px-3 py-1.5 font-medium">At</th>
                    <th className="w-36 px-2 py-1.5 font-medium">Event</th>
                    <th className="px-2 py-1.5 font-medium">Hook</th>
                    <th className="w-20 px-2 py-1.5 font-medium">Result</th>
                    <th className="w-20 px-3 py-1.5 text-right font-medium">Took</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                  {state.recent.slice(0, 40).map((run, index) => (
                    <tr key={index} title={run.detail ?? undefined}>
                      <td className="px-3 py-1.5 whitespace-nowrap text-muted-foreground tabular-nums">{new Date(run.at).toLocaleTimeString()}</td>
                      <td className="truncate px-2 py-1.5 font-mono">
                        {run.event}
                        {run.target ? <span className="text-muted-foreground"> · {run.target}</span> : null}
                      </td>
                      <td className="truncate px-2 py-1.5 font-mono text-muted-foreground">
                        {run.hook}
                        {run.detail ? <span className="text-foreground"> — {run.detail}</span> : null}
                      </td>
                      <td className={cn("px-2 py-1.5", resultTone[run.result])}>{run.result}</td>
                      <td className="px-3 py-1.5 text-right whitespace-nowrap text-muted-foreground tabular-nums">{run.ms} ms</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="text-xs font-medium text-muted-foreground">Adding a hook</h3>
          <p className="text-xs text-muted-foreground">
            Add a <code>hooks</code> block to your settings (every project) or a project's <code>.evo/settings.json</code>. A
            hook gets the event as JSON on stdin. Exit 0 lets it go on (print JSON to decide more), exit 2 blocks with what it
            wrote to stderr, other exits are reported but do not block. A matcher picks tools by name, like{" "}
            <code>bash|edit</code> or <code>mcp__github__.*</code>.
          </p>
          <pre className="overflow-x-auto rounded-xl bg-muted/50 p-3 font-mono text-[11px] leading-relaxed dark:bg-accent/30">{EXAMPLE}</pre>
        </section>
      </div>
    </div>
  );
}
