// Undo / redo / version history of an Office document, in the viewer's
// toolbar (docs/features/office-v3-parity/sdd.md, FR-12; port of v3
// web/src/components/document-version-controls.tsx).
//
// The engine keeps every settled save of the file as a version
// (`document_versions_get` / `document_versions_act`, crates/evo-office
// versions.rs). Stepping or restoring writes that version back to the
// folder: the file's mtime changes and the viewer re-renders; `onChange` lets
// it refresh at once as well.
//
// Props: `path` (absolute or relative to the chat's working folder),
// `revision` (the file's mtime: every save refreshes the history), `chatId`
// (refetch when the chat changes), `buttonClassName`, `onChange`.

import * as React from "react";
import { HistoryIcon, Redo2Icon, Undo2Icon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";

export interface DocumentVersion {
  id: string;
  size: number;
  /** When it was recorded: seconds since the epoch (milliseconds are accepted too). */
  createdAt: number;
  label: string;
  /** "baseline" (the file as first seen), "change", "checkpoint", … */
  source: string;
}

export interface DocumentVersions {
  path: string;
  head: string | null;
  canUndo: boolean;
  canRedo: boolean;
  /** Oldest first. */
  versions: DocumentVersion[];
}

type Action = { action: "undo" } | { action: "redo" } | { action: "restore"; versionId: string };

function versionTitle(version: DocumentVersion, index: number): string {
  if (version.label) return version.label;
  if (version.source === "baseline" || index === 0) return "Original";
  return `Version ${index + 1}`;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatWhen(stamp: number): string {
  const date = new Date(stamp > 1e12 ? stamp : stamp * 1000);
  const sameDay = date.toDateString() === new Date().toDateString();
  return sameDay
    ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function message(error: unknown): string {
  return String(error instanceof Error ? error.message : error).replace(/^Error:\s*/, "");
}

export interface DocumentVersionControlsProps {
  /** The document, absolute or relative to the chat's working folder. */
  path: string;
  /** The file's mtime (anything that changes on every save): refreshes the history. */
  revision: number | string | undefined;
  /** The chat the file belongs to (engine-store `activeId`). */
  chatId?: string | null;
  buttonClassName?: string;
  /** After undo, redo or restore wrote another version to the file. */
  onChange?(): void;
}

export function DocumentVersionControls({ path, revision, chatId, buttonClassName, onChange }: DocumentVersionControlsProps) {
  const [data, setData] = React.useState<DocumentVersions | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [problem, setProblem] = React.useState<string | null>(null);
  const ready = useEngineStore((s) => (s.activeId ? s.runtimes[s.activeId]?.status === "ready" : false));
  const versions = data?.versions ?? [];

  React.useEffect(() => {
    if (!ready) return;
    let live = true;
    useEngineStore
      .getState()
      .request<DocumentVersions>("document_versions_get", { path })
      .then((next) => live && setData(next))
      // An engine without versions (or a file it cannot read): no history.
      .catch(() => live && setData(null));
    return () => {
      live = false;
    };
  }, [path, revision, chatId, ready]);

  async function act(change: Action) {
    setBusy(true);
    setProblem(null);
    try {
      const next = await useEngineStore.getState().request<DocumentVersions>("document_versions_act", { path, ...change });
      setData(next);
      onChange?.();
    } catch (error) {
      setProblem(message(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative flex items-center gap-0.5" role="group" aria-label="Document versions">
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={() => void act({ action: "undo" })}
        disabled={!data?.canUndo || busy}
        aria-label="Undo last change to this file"
        title="Undo last change"
        className={buttonClassName}
      >
        <Undo2Icon />
      </Button>
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={() => void act({ action: "redo" })}
        disabled={!data?.canRedo || busy}
        aria-label="Redo change to this file"
        title="Redo"
        className={buttonClassName}
      >
        <Redo2Icon />
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="ghost"
              size="icon-sm"
              disabled={versions.length === 0}
              aria-label="Version history"
              title="Version history"
              className={cn(buttonClassName, "data-popup-open:bg-accent data-popup-open:text-foreground")}
            />
          }
        >
          {busy ? <Spinner /> : <HistoryIcon />}
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-72 rounded-lg">
          <DropdownMenuGroup aria-label="Versions of this file">
            <DropdownMenuLabel className="text-[11px] font-medium">
              {versions.length} version{versions.length === 1 ? "" : "s"} · restoring keeps later ones until the next edit
            </DropdownMenuLabel>
            <div className="max-h-72 overflow-y-auto">
              {versions
                .map((version, index) => ({ version, index }))
                .reverse()
                .map(({ version, index }) => {
                  const current = version.id === data?.head;
                  return (
                    <DropdownMenuItem
                      key={version.id}
                      disabled={current || busy}
                      aria-current={current || undefined}
                      onClick={() => void act({ action: "restore", versionId: version.id })}
                      className={cn("items-start rounded-md text-xs", current && "bg-brand/8 data-disabled:opacity-100")}
                    >
                      <span
                        className={cn(
                          "mt-1 size-2 shrink-0 rounded-full border border-muted-foreground",
                          current && "border-brand bg-brand",
                        )}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate">{versionTitle(version, index)}</span>
                        <span className="block text-[10px] text-muted-foreground">
                          {formatWhen(version.createdAt)} · {formatSize(version.size)}
                          {current ? " · current" : ""}
                        </span>
                      </span>
                    </DropdownMenuItem>
                  );
                })}
            </div>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
      {problem && (
        <span role="alert" className="sr-only">
          {problem}
        </span>
      )}
    </div>
  );
}
