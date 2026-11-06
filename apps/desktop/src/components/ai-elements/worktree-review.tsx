import * as React from "react";
import { GitBranchIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CodeBlock, CodeBlockContent, CodeBlockLine } from "@/components/ui/code-block";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { notify } from "@/features/notifications/notify";
import { worktrees, type WorktreeChanges } from "@/lib/worktrees";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";

// Review what a subagent or a nested session changed in its worktree, then
// apply it to the workspace (uncommitted) or discard it. Uses the shell's
// worktree commands (src-tauri/src/worktrees.rs).

export type WorktreeOutcome = "applied" | "discarded";

function PatchView({ patch }: { patch: string }) {
  const lines = patch.split("\n");
  return (
    <CodeBlock size="sm">
      <CodeBlockContent className="max-h-[45vh]" data-selectable>
        {lines.map((line, index) => {
          const header = line.startsWith("diff --git") || line.startsWith("index ") || line.startsWith("@@");
          const variant =
            line.startsWith("+") && !line.startsWith("+++")
              ? "added"
              : line.startsWith("-") && !line.startsWith("---")
                ? "removed"
                : "default";
          return (
            <CodeBlockLine
              key={index}
              variant={variant}
              className={cn(header && "text-muted-foreground", line.startsWith("diff --git") && "mt-2 font-medium")}
            >
              {/* The line draws its own +/− marker. */}
              {(variant === "default" ? line : line.slice(1)) || " "}
            </CodeBlockLine>
          );
        })}
      </CodeBlockContent>
    </CodeBlock>
  );
}

export function WorktreeReview({
  open,
  onOpenChange,
  repo,
  path,
  branch,
  onSettled,
}: {
  open: boolean;
  onOpenChange(open: boolean): void;
  /** A folder of the repository the worktree belongs to. */
  repo: string;
  path: string;
  branch?: string;
  onSettled?(outcome: WorktreeOutcome): void;
}) {
  const [changes, setChanges] = React.useState<WorktreeChanges | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<WorktreeOutcome | null>(null);
  const [confirmDiscard, setConfirmDiscard] = React.useState(false);
  const settle = useUiStore((s) => s.settleWorktree);

  React.useEffect(() => {
    if (!open) return;
    setChanges(null);
    setError(null);
    setConfirmDiscard(false);
    worktrees
      .changes(repo, path)
      .then(setChanges)
      .catch((e: unknown) => setError(String(e)));
  }, [open, repo, path]);

  async function finish(outcome: WorktreeOutcome) {
    setBusy(outcome);
    setError(null);
    try {
      if (outcome === "applied") {
        const done = await worktrees.apply(repo, path);
        notify({
          source: "worktrees",
          level: "success",
          title: "Changes applied",
          body: `${done.files} ${done.files === 1 ? "file" : "files"} changed in your workspace (not committed).`,
        });
      } else {
        await worktrees.discard(repo, path);
      }
      settle(path, outcome);
      onSettled?.(outcome);
      onOpenChange(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  const empty = changes && changes.files.length === 0;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] grid-rows-[auto_1fr_auto] sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitBranchIcon className="size-4 text-muted-foreground" />
            Review changes
          </DialogTitle>
          <DialogDescription className="truncate font-mono text-xs" title={path}>
            {branch ? `${branch} · ` : ""}
            {path}
          </DialogDescription>
        </DialogHeader>
        <div className="flex min-h-0 flex-col gap-3 overflow-y-auto">
          {!changes && !error && <p className="text-muted-foreground">Reading the changes…</p>}
          {empty && <p className="text-muted-foreground">Nothing changed in this worktree.</p>}
          {changes && !empty && (
            <>
              <p className="text-[13px] text-muted-foreground">
                {changes.files.length} {changes.files.length === 1 ? "file" : "files"} ·{" "}
                <span className="text-status-ok">+{changes.added}</span>{" "}
                <span className="text-destructive">−{changes.removed}</span> since{" "}
                <code className="font-mono">{changes.base.slice(0, 8)}</code>
              </p>
              <ul className="flex flex-col gap-0.5 font-mono text-xs">
                {changes.files.map((file) => (
                  <li key={file.path} className="flex items-center gap-2">
                    <span
                      className={cn(
                        "w-14 shrink-0 text-[11px] uppercase",
                        file.status === "added" ? "text-status-ok" : file.status === "deleted" ? "text-destructive" : "text-muted-foreground",
                      )}
                    >
                      {file.status}
                    </span>
                    <span className="truncate">{file.path}</span>
                    <span className="ml-auto shrink-0 text-muted-foreground tabular-nums">
                      {file.added === null ? "binary" : `+${file.added} −${file.removed}`}
                    </span>
                  </li>
                ))}
              </ul>
              <PatchView patch={changes.patch} />
              {changes.truncated && (
                <p className="text-xs text-muted-foreground">The patch is long; only its start is shown. Applying uses all of it.</p>
              )}
            </>
          )}
          {error && <p className="text-[13px] whitespace-pre-wrap text-destructive">{error}</p>}
        </div>
        <DialogFooter className="items-center">
          {confirmDiscard ? (
            <>
              <span className="mr-auto text-[13px] text-muted-foreground">Throw these changes and the worktree away?</span>
              <Button variant="outline" onClick={() => setConfirmDiscard(false)}>
                Keep
              </Button>
              <Button variant="destructive" disabled={busy !== null} onClick={() => void finish("discarded")}>
                {busy === "discarded" ? "Discarding…" : "Discard"}
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="ghost"
                className="mr-auto text-destructive hover:text-destructive"
                disabled={busy !== null}
                onClick={() => setConfirmDiscard(true)}
              >
                Discard…
              </Button>
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Close
              </Button>
              <Button disabled={busy !== null || !changes || Boolean(empty)} onClick={() => void finish("applied")}>
                {busy === "applied" ? "Applying…" : "Apply to workspace"}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
