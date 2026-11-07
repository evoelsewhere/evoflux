// Files tool: the open files (tabs), the explorer's expanded folders, and each
// open file's load/save state, and what git says about the tree's folder
// (docs/features/files-git/spec.md). The editor text itself lives in CodeMirror
// states kept beside the store (features/files/code-editor.tsx).

import { create } from "zustand";
import { persist } from "zustand/middleware";
import { isConflict, readFile, samePath, statFile, writeFile, type FileContent } from "@/features/files/fs";
import { buildDecorations, type GitDecorations } from "@/features/files/git-state";
import { git } from "@/lib/git";
import { useUiStore } from "./ui-store";

export interface OpenFile {
  path: string;
  content: FileContent | null;
  loading: boolean;
  error?: string;
  /** Edited since the last load or save. */
  dirty: boolean;
  saving: boolean;
  /** Changed on disk while it had unsaved edits: Override or Discard. */
  conflict: boolean;
  /** Bumped when the text is (re)loaded from disk, so the editor takes it. */
  revision: number;
}

interface FilesStore {
  /** Open files in tab order. */
  tabs: string[];
  /** The visible file; `null` shows the empty editor. */
  active: string | null;
  files: Record<string, OpenFile>;
  /** Expanded folders in the explorer. */
  expanded: string[];
  /** Save edits as you type (otherwise Ctrl/⌘+S). */
  autoSave: boolean;
  /** The folder tree beside the editor (wide panels). */
  treeVisible: boolean;
  /** The tree's width in pixels. */
  treeWidth: number;
  /** A line to scroll to and mark once `path` shows. */
  reveal: { path: string; line: number; nonce: number } | null;
  /** Git marks for the tree's folder; `null` outside a repository or before the first read. */
  git: GitDecorations | null;
  /** Re-read `git status` for `root`; `full` also re-reads the ignored paths. */
  refreshGit(root: string, full?: boolean): Promise<void>;
  /** Open `path` (at `line`, 1-based) in the Files tool and show it. */
  open(path: string, line?: number): Promise<void>;
  close(path: string): void;
  closeAll(): void;
  select(path: string | null): void;
  toggleFolder(path: string, open?: boolean): void;
  /** Fold every folder except `keep`. */
  collapseAll(keep?: string): void;
  /** Unfold every folder in `paths`. */
  expand(paths: string[]): void;
  setTreeVisible(on: boolean): void;
  setTreeWidth(width: number): void;
  setAutoSave(on: boolean): void;
  /** Read from disk (again), dropping unsaved edits. */
  load(path: string): Promise<void>;
  markDirty(path: string, dirty: boolean): void;
  /** Save `text`; with `force`, overwrite a change made on disk meanwhile. */
  save(path: string, text: string, force?: boolean): Promise<boolean>;
  /** Pick up changes made on disk (by the agent, git, another editor). */
  checkDisk(path: string): Promise<void>;
  consumeReveal(): void;
}

const blank = (path: string): OpenFile => ({
  path,
  content: null,
  loading: true,
  dirty: false,
  saving: false,
  conflict: false,
  revision: 0,
});

/** Every this many status reads, the ignored list is read again too. */
const IGNORED_EVERY = 5;
/** One git read at a time; a request made meanwhile runs once after it. */
const gitRun = {
  busy: false,
  again: null as { root: string; full: boolean } | null,
  root: "",
  ignored: null as string[] | null,
  reads: 0,
  /** What the last result looked like, so an unchanged repository does not re-render the tree. */
  signature: "",
  warned: "",
};

/** The tab already open for `path`, whatever its slashes or case. */
const openKey = (tabs: string[], path: string) => tabs.find((tab) => samePath(tab, path));

export const useFilesStore = create<FilesStore>()(
  persist(
    (set, get) => {
      const patch = (path: string, change: Partial<OpenFile>) =>
        set((s) => (s.files[path] ? { files: { ...s.files, [path]: { ...s.files[path], ...change } } } : s));

      return {
        tabs: [],
        active: null,
        files: {},
        expanded: [],
        autoSave: true,
        treeVisible: true,
        treeWidth: 280,
        reveal: null,
        git: null,

        async refreshGit(root, full = false) {
          if (gitRun.busy) {
            gitRun.again = { root, full: full || (gitRun.again?.root === root && gitRun.again.full) };
            return;
          }
          gitRun.busy = true;
          try {
            const fresh = gitRun.root !== root;
            const readIgnored = full || fresh || ++gitRun.reads % IGNORED_EVERY === 0;
            const [status, ignored] = await Promise.all([
              git.status(root),
              readIgnored ? git.ignored(root) : Promise.resolve(gitRun.ignored),
            ]);
            gitRun.root = root;
            gitRun.ignored = ignored;
            const signature = JSON.stringify([
              root,
              status?.root,
              status?.head,
              status?.files.map((f) => `${f.status}:${f.path}`),
              ignored,
            ]);
            if (signature !== gitRun.signature) {
              gitRun.signature = signature;
              set({ git: buildDecorations(status, ignored) });
            }
          } catch (error) {
            // `git` missing or failing: no marks, one log line per folder.
            if (gitRun.warned !== root) console.warn("Files: git status unavailable:", error);
            gitRun.warned = root;
            gitRun.root = root;
            gitRun.signature = "";
            if (get().git) set({ git: null });
          } finally {
            gitRun.busy = false;
            const next = gitRun.again;
            gitRun.again = null;
            if (next) void get().refreshGit(next.root, next.full);
          }
        },

        async open(path, line) {
          const key = openKey(get().tabs, path) ?? path;
          const known = get().files[key];
          set((s) => ({
            tabs: s.tabs.includes(key) ? s.tabs : [...s.tabs, key],
            active: key,
            files: known ? s.files : { ...s.files, [key]: blank(key) },
            reveal: line && line > 0 ? { path: key, line, nonce: Date.now() } : s.reveal,
          }));
          useUiStore.getState().openPanel("files");
          if (!known || (known.error && !known.loading)) await get().load(key);
          else void get().checkDisk(key);
        },

        close(path) {
          set((s) => {
            const index = s.tabs.indexOf(path);
            const tabs = s.tabs.filter((t) => t !== path);
            const { [path]: _closed, ...files } = s.files;
            const active = s.active === path ? (tabs[Math.min(index, tabs.length - 1)] ?? null) : s.active;
            return { tabs, files, active };
          });
        },

        closeAll: () => set({ tabs: [], files: {}, active: null }),
        select: (active) => set({ active }),

        toggleFolder(path, open) {
          set((s) => {
            const isOpen = s.expanded.includes(path);
            const next = open ?? !isOpen;
            if (next === isOpen) return s;
            return { expanded: next ? [...s.expanded, path] : s.expanded.filter((p) => p !== path) };
          });
        },

        collapseAll: (keep) => set({ expanded: keep ? [keep] : [] }),
        expand: (paths) =>
          set((s) => {
            const add = paths.filter((p) => !s.expanded.includes(p));
            return add.length ? { expanded: [...s.expanded, ...add] } : s;
          }),
        setTreeVisible: (treeVisible) => set({ treeVisible }),
        setTreeWidth: (treeWidth) => set({ treeWidth: Math.round(treeWidth) }),

        setAutoSave: (autoSave) => set({ autoSave }),

        async load(path) {
          if (!get().files[path]) return;
          patch(path, { loading: true, error: undefined });
          try {
            const content = await readFile(path);
            patch(path, {
              content,
              loading: false,
              dirty: false,
              conflict: false,
              revision: (get().files[path]?.revision ?? 0) + 1,
            });
          } catch (error) {
            patch(path, { loading: false, error: String(error) });
          }
        },

        markDirty(path, dirty) {
          if (get().files[path] && get().files[path].dirty !== dirty) patch(path, { dirty });
        },

        async save(path, text, force = false) {
          const file = get().files[path];
          if (!file || file.content?.kind !== "text") return false;
          patch(path, { saving: true });
          try {
            const mtime = await writeFile(path, text, force ? undefined : file.content.mtime);
            const current = get().files[path];
            if (current?.content?.kind === "text") {
              patch(path, {
                saving: false,
                conflict: false,
                content: { ...current.content, text, mtime, size: new Blob([text]).size },
              });
            }
            return true;
          } catch (error) {
            if (isConflict(error)) patch(path, { saving: false, conflict: true });
            else patch(path, { saving: false, error: String(error) });
            return false;
          }
        },

        async checkDisk(path) {
          const file = get().files[path];
          if (!file?.content || file.loading || file.saving) return;
          const stat = await statFile(path).catch(() => null);
          if (!stat) return;
          if (!stat.exists) {
            patch(path, { error: "This file was deleted or moved." });
            return;
          }
          if (stat.mtime === file.content.mtime) {
            if (file.error === "This file was deleted or moved.") patch(path, { error: undefined });
            return;
          }
          // Unsaved edits: ask. Otherwise take the new version.
          if (file.dirty) patch(path, { conflict: true });
          else await get().load(path);
        },

        consumeReveal: () => set({ reveal: null }),
      };
    },
    {
      name: "evo.files",
      partialize: (state) => ({
        autoSave: state.autoSave,
        expanded: state.expanded,
        treeVisible: state.treeVisible,
        treeWidth: state.treeWidth,
      }),
    },
  ),
);

/** Open a file in the Files tool, at `line` when given. */
export const openFile = (path: string, line?: number) => useFilesStore.getState().open(path, line);
