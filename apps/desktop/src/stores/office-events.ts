// Office files a chat's engine saw change on disk (event `office_file_changed`,
// crates/evo-engine/src/fs_watch.rs; docs/features/office-v3-parity/spec.md).
// engine-store routes the event here; the Files tool listens (open previews
// re-render, a document the agent creates opens by itself). No React, no
// imports, so any store can use it without an import cycle.

export interface OfficeFileChange {
  kind: "added" | "modified" | "deleted";
  /** Relative to the chat's working folder, with forward slashes. */
  path: string;
}

type Listener = (chat: string, changes: OfficeFileChange[]) => void;

const listeners = new Set<Listener>();

/** Listen to Office file changes of every chat; returns the unsubscribe. */
export function onOfficeFileChanged(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const KINDS = new Set(["added", "modified", "deleted"]);

/** Called by engine-store with the event's `changes` (untrusted shape: checked here). */
export function emitOfficeFileChanged(chat: string, changes: unknown): void {
  if (!Array.isArray(changes)) return;
  const valid = changes.filter(
    (change): change is OfficeFileChange =>
      !!change && typeof change === "object" && KINDS.has(change.kind) && typeof change.path === "string" && !!change.path,
  );
  if (valid.length === 0) return;
  for (const listener of listeners) {
    try {
      listener(chat, valid);
    } catch (error) {
      console.warn("office_file_changed listener failed:", error);
    }
  }
}
