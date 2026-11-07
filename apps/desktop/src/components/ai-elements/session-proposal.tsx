import * as React from "react";
import { ArrowUpRightIcon, MessagesSquareIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ToolPart } from "@/features/chat/transcript";
import { useEngineStore } from "@/stores/engine-store";
import { useSessionStore } from "@/stores/session-store";
import { useUiStore } from "@/stores/ui-store";

// A `start_session` call's card. By default the agent only proposes a nested
// session: the person starts it here (or dismisses it). Started ones link to
// the session. The proposal's content lives in the call's result
// (`details.externalToolResult.structuredContent`), so it survives a reload.

interface Proposal {
  status: "proposed" | "started";
  proposalId?: string;
  sessionId?: string;
  title: string;
  prompt: string;
  context?: "fresh" | "fork";
  worktree?: boolean;
}

export const proposalOf = (part: ToolPart): Proposal | undefined => {
  const structured = part.details?.externalToolResult?.structuredContent;
  return structured && typeof structured === "object" && typeof structured.title === "string"
    ? (structured as Proposal)
    : undefined;
};

export function SessionProposal({ part }: { part: ToolPart }) {
  const proposal = proposalOf(part);
  const chat = useEngineStore((s) => s.activeId);
  const startChildSession = useEngineStore((s) => s.startChildSession);
  const selectSession = useEngineStore((s) => s.selectSession);
  const outcome = useUiStore((s) => (proposal?.proposalId ? s.proposals[proposal.proposalId] : undefined));
  const settle = useUiStore((s) => s.settleProposal);
  const sessionId = proposal?.status === "started" ? proposal.sessionId : outcome?.sessionId;
  const live = useSessionStore((s) => (sessionId ? s.sessions.find((x) => x.id === sessionId) : undefined));
  const [starting, setStarting] = React.useState(false);
  const [expanded, setExpanded] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  if (!proposal) return null;

  const started = Boolean(sessionId);
  const dismissed = outcome?.status === "dismissed";

  async function start() {
    if (!chat || !proposal?.proposalId) return;
    setStarting(true);
    const id = await startChildSession(chat, {
      title: proposal.title,
      prompt: proposal.prompt,
      context: proposal.context,
      worktree: proposal.worktree,
    })
      .catch((error: unknown) => {
        setError(String(error));
        return null;
      })
      .finally(() => setStarting(false));
    if (id) settle(proposal.proposalId, { status: "started", sessionId: id });
  }

  return (
    <div className="flex max-w-xl flex-col gap-2.5 rounded-xl bg-card px-4 py-3.5 shadow-border-small">
      <div className="flex items-start gap-2.5">
        <MessagesSquareIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{live?.title ?? proposal.title}</p>
          <p className="text-xs text-muted-foreground">
            {started
              ? "Nested session"
              : dismissed
                ? "Dismissed"
                : `Proposed session${proposal.context === "fork" ? " · forks this conversation" : ""}${
                    proposal.worktree ? " · in its own worktree" : ""
                  }`}
          </p>
        </div>
      </div>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="text-left text-[13px] whitespace-pre-wrap text-muted-foreground hover:text-foreground"
      >
        <span className={expanded ? undefined : "line-clamp-3"}>{proposal.prompt}</span>
      </button>
      {error && <p className="text-[13px] text-destructive">{error}</p>}
      {!dismissed && (
        <div className="flex items-center gap-2">
          {started ? (
            <Button variant="outline" size="sm" className="h-7 gap-1.5" onClick={() => void selectSession(sessionId!)}>
              Open session
              <ArrowUpRightIcon className="size-3.5" />
            </Button>
          ) : (
            <>
              <Button size="sm" className="h-7" disabled={starting || !chat} onClick={() => void start()}>
                {starting ? "Starting…" : "Start session"}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-7"
                onClick={() => proposal.proposalId && settle(proposal.proposalId, { status: "dismissed" })}
              >
                Dismiss
              </Button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
