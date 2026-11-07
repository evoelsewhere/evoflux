import * as React from "react";
import { GitBranchIcon, SquareIcon } from "lucide-react";
import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import { useEngineStore } from "@/stores/engine-store";
import { useUiStore } from "@/stores/ui-store";
import { WorktreeReview } from "./worktree-review";
import { Trace } from "@/components/ui/trace";
import type { ToolPart } from "@/features/chat/transcript";
import { Tool } from "./tool";

// The body of an `agent` tool call: what the subagent is doing (its own tool
// calls as nested rows, the end of its latest text), how much it has done,
// and its report. The engine streams this as `details.child`
// (crates/evo-engine/src/agent_tool.rs) and keeps it on the result, so a
// reopened chat shows it too.

export interface ChildRun {
  agentId?: string;
  background?: boolean;
  agentType?: string;
  description?: string;
  model?: string;
  status?: "running" | "done" | "error" | "cancelled";
  turns?: number;
  toolUses?: number;
  usage?: { totalTokens?: number; cost?: number };
  startedAt?: number;
  endedAt?: number | null;
  tools?: { callId: string; name: string; args?: Record<string, unknown>; phase: ToolPart["phase"] }[];
  text?: string;
  worktree?: { path?: string; branch?: string; kept?: boolean } | null;
  error?: string | null;
}

export const childRun = (part: ToolPart): ChildRun | undefined =>
  part.details && typeof part.details === "object" ? (part.details.child as ChildRun | undefined) : undefined;

/** Rows shown while running; the rest fold into "N earlier steps". */
const LIVE_ROWS = 6;

function seconds(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

function tokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}k` : String(n);
}

/** Re-render every second while running, for the elapsed time. */
function useTick(active: boolean) {
  const [, setTick] = React.useState(0);
  React.useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
}

export function AgentRun({ part, live }: { part: ToolPart; live: boolean }) {
  const child = childRun(part);
  useTick(live);
  const chat = useEngineStore((s) => s.activeId);
  const cancel = useEngineStore((s) => s.cancelBackgroundAgent);
  // The repository the worktree belongs to: this chat's folder.
  const repo = useEngineStore((s) => s.cwd);
  const settled = useUiStore((s) => (child?.worktree?.path ? s.settledWorktrees[child.worktree.path] : undefined));
  const [reviewing, setReviewing] = React.useState(false);
  // A background agent's call ended with "started"; its report is its last text.
  const report = child?.background ? (child.status === "done" ? child.text?.trim() : undefined) : part.output;
  const failed = child?.background ? child.status === "error" || child.status === "cancelled" : part.phase === "error";
  const rows = child?.tools ?? [];
  const [all, setAll] = React.useState(false);
  const hidden = live && !all ? Math.max(0, rows.length - LIVE_ROWS) : 0;
  const shown = rows.slice(hidden);
  const elapsed = child?.startedAt ? (child.endedAt ?? Date.now()) - child.startedAt : 0;
  const latest = child?.text?.trim().split("\n").filter(Boolean).at(-1);
  const facts = [
    child?.agentType,
    child?.toolUses ? `${child.toolUses} tool ${child.toolUses === 1 ? "use" : "uses"}` : undefined,
    child?.usage?.totalTokens ? `${tokens(child.usage.totalTokens)} tokens` : undefined,
    elapsed ? seconds(elapsed) : undefined,
    child?.model,
  ].filter(Boolean);

  return (
    <div className="flex flex-col gap-2.5">
      {(rows.length > 0 || hidden > 0) && (
        <Trace className="gap-1.5">
          {hidden > 0 && (
            <button
              type="button"
              onClick={() => setAll(true)}
              className="w-fit text-xs text-muted-foreground hover:text-foreground"
            >
              {hidden} earlier {hidden === 1 ? "step" : "steps"}
            </button>
          )}
          {shown.map((row) => (
            <Tool
              key={row.callId}
              lineOnly
              streaming={live}
              part={{
                kind: "tool",
                key: row.callId,
                callId: row.callId,
                name: row.name,
                args: row.args ?? {},
                argsText: "",
                phase: row.phase,
                output: "",
                startedAt: 0,
              }}
            />
          ))}
        </Trace>
      )}
      {live && latest && <p className="line-clamp-2 text-[13px] text-muted-foreground italic">{latest}</p>}
      {!live && !failed && report && (
        <div className="rounded-lg bg-muted/40 px-3.5 py-3 shadow-hairline">
          <Markdown>{report.replace(/\n\n\[Its changes are in the worktree [^\]]*\]$/, "")}</Markdown>
        </div>
      )}
      {!live && failed && (child?.error || part.output) && (
        <p className="text-[13px] text-destructive">
          {child?.status === "cancelled" ? "Cancelled" : (child?.error ?? part.output)}
        </p>
      )}
      {live && child?.background && child.agentId && chat && (
        <Button
          variant="outline"
          size="sm"
          className="h-7 w-fit gap-1.5 text-xs"
          onClick={() => void cancel(chat, child.agentId!)}
        >
          <SquareIcon className="size-3" />
          Stop agent
        </Button>
      )}
      {child?.worktree?.kept && (
        <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
          <GitBranchIcon className="size-3.5 shrink-0" />
          {settled ? (
            <span>
              Changes {settled} · <code className="font-mono">{child.worktree.branch}</code>
            </span>
          ) : (
            <>
              <span className="min-w-0 truncate" title={child.worktree.path}>
                Changes kept on <code className="font-mono">{child.worktree.branch}</code>
              </span>
              {!live && repo && child.worktree.path && (
                <Button variant="outline" size="sm" className="h-6 shrink-0 px-2 text-xs" onClick={() => setReviewing(true)}>
                  Review changes
                </Button>
              )}
            </>
          )}
          {repo && child.worktree.path && (
            <WorktreeReview
              open={reviewing}
              onOpenChange={setReviewing}
              repo={repo}
              path={child.worktree.path}
              branch={child.worktree.branch}
            />
          )}
        </div>
      )}
      {facts.length > 0 && <p className="text-xs text-muted-foreground tabular-nums">{facts.join(" · ")}</p>}
    </div>
  );
}
