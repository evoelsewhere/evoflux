// Live previews for Office files the agent writes (port of v3
// web/src/hooks/useGeneratedDocumentWatcher.ts; docs/features/office-v3-parity
// /sdd.md FR-9). The engine reports Office files changing in a chat's folder
// (`office_file_changed`, stores/office-events.ts) — it sees files written by
// a script mid-run, long before the tool call ends. For each change:
//
// 1. an open preview of that file checks the disk, so it picks up each save
//    while the agent is still working (a deck built slide by slide redraws
//    after every slide);
// 2. a document the agent just created opens in Files, once per file, while
//    the chat's turn runs — unless the setting is off or another side-panel
//    tool is in front.
//
// Loaded with the Files tool (features/files/index.ts), which the side panel
// imports at startup.

import { useEngineStore } from "@/stores/engine-store";
import { useFilesStore } from "@/stores/files-store";
import { onOfficeFileChanged, type OfficeFileChange } from "@/stores/office-events";
import { autoOpenGeneratedEnabled } from "@/stores/office-store";
import { useUiStore } from "@/stores/ui-store";
import { resolvePath, samePath } from "../fs";

const OFFICE_DOCUMENT = /\.(pptx|docx|xlsx)$/i;

/** Per chat: the documents already opened for it (v3 kept one set per watched session). */
const opened = new Map<string, Set<string>>();

/** Decide whether a newly created document should take over the side panel. */
export async function shouldOpenGeneratedDocument(chat: string): Promise<boolean> {
  const engine = useEngineStore.getState();
  if (engine.activeId !== chat || !engine.runtimes[chat]?.transcript.busy) return false;
  if (!(await autoOpenGeneratedEnabled())) return false;
  const ui = useUiStore.getState();
  // Never pull the person out of another tool they are looking at.
  return !ui.rightPanelOpen || ui.activePanel === null || ui.activePanel === "files";
}

function handleChanges(chat: string, changes: OfficeFileChange[]): void {
  const root = useEngineStore.getState().runtimes[chat]?.cwd;
  if (!root) return;
  const documents = changes.filter((change) => change.kind !== "deleted" && OFFICE_DOCUMENT.test(change.path));
  if (documents.length === 0) return;

  const files = useFilesStore.getState();
  for (const change of documents) {
    const tab = files.tabs.find((open) => samePath(open, resolvePath(root, change.path)));
    if (tab) void files.checkDisk(tab);
  }

  let seen = opened.get(chat);
  if (!seen) opened.set(chat, (seen = new Set()));
  const created = documents.find((change) => change.kind === "added" && !seen.has(change.path));
  if (!created) return;
  void shouldOpenGeneratedDocument(chat).then((open) => {
    if (!open || seen.has(created.path)) return;
    seen.add(created.path);
    void useFilesStore.getState().open(resolvePath(root, created.path));
  });
}

const unsubscribe = onOfficeFileChanged(handleChanges);
import.meta.hot?.dispose(unsubscribe);
