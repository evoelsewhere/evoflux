// What the Files tree shows of git: changed files, folders holding changes,
// ignored paths. Pure functions over `git_status` / `git_ignored` output; the
// store keeps the result per tree root. Design: docs/features/files-git/sdd.md.

import type { RepoStatus } from "@/lib/git";

export type FileGitState = "modified" | "added" | "deleted";

export interface GitDecorations {
  /** Repository top folder, as a key (see `pathKey`). */
  root: string;
  /** Short commit id of HEAD; `null` before the first commit. */
  head: string | null;
  /** Changed file → its state. */
  files: Map<string, FileGitState>;
  /** Folder holding changes → `added` when everything inside is new, else `modified`. */
  folders: Map<string, "modified" | "added">;
  ignoredFiles: Set<string>;
  /** Ignored folders (without the trailing `/`); everything below is ignored too. */
  ignoredDirs: Set<string>;
  caseless: boolean;
}

/** What one tree row shows; a string so store selectors stay stable. */
export type RowGit = "" | FileGitState | "ignored" | "folder-modified" | "folder-added";

const isCaseless = (path: string) => /^[a-z]:/i.test(path);

/** A comparable path: forward slashes, no trailing slash, lower case on Windows drives. */
export function pathKey(path: string, caseless = isCaseless(path)): string {
  const p = path.replace(/\\/g, "/").replace(/\/+$/, "");
  return caseless ? p.toLowerCase() : p;
}

/** Parent of a key, or `null` at the top. */
const parentKey = (key: string) => {
  const at = key.lastIndexOf("/");
  return at > 0 ? key.slice(0, at) : null;
};

export function buildDecorations(status: RepoStatus | null, ignored: string[] | null): GitDecorations | null {
  if (!status) return null;
  const caseless = isCaseless(status.root);
  const root = pathKey(status.root, caseless);
  const files = new Map<string, FileGitState>();
  const folders = new Map<string, "modified" | "added">();
  for (const change of status.files) {
    const key = pathKey(`${root}/${change.path}`, caseless);
    files.set(key, change.status);
    const folderState = change.status === "added" ? "added" : "modified";
    for (let dir = parentKey(key); dir && dir.length >= root.length; dir = parentKey(dir)) {
      const known = folders.get(dir);
      const next = known && known !== folderState ? "modified" : folderState;
      // Unchanged here means unchanged above: ancestors were merged when it was set.
      if (known === next) break;
      folders.set(dir, next);
    }
  }
  const ignoredFiles = new Set<string>();
  const ignoredDirs = new Set<string>();
  for (const path of ignored ?? []) {
    if (path.endsWith("/")) ignoredDirs.add(pathKey(path, caseless));
    else ignoredFiles.add(pathKey(path, caseless));
  }
  return { root, head: status.head, files, folders, ignoredFiles, ignoredDirs, caseless };
}

/** The git mark for the tree row of `path`. */
export function rowGit(deco: GitDecorations | null, path: string, dir: boolean): RowGit {
  if (!deco) return "";
  const key = pathKey(path, deco.caseless);
  if (key !== deco.root && !key.startsWith(`${deco.root}/`)) return "";
  if (!dir) {
    const state = deco.files.get(key);
    if (state) return state;
    if (deco.ignoredFiles.has(key)) return "ignored";
  } else {
    const state = deco.folders.get(key);
    if (state) return state === "added" ? "folder-added" : "folder-modified";
  }
  for (let at: string | null = dir ? key : parentKey(key); at && at.length > deco.root.length; at = parentKey(at)) {
    if (deco.ignoredDirs.has(at)) return "ignored";
  }
  return "";
}

/** The state of one file (for the editor: an untracked file is all "added"). */
export function fileGit(deco: GitDecorations | null, path: string): FileGitState | null {
  if (!deco) return null;
  return deco.files.get(pathKey(path, deco.caseless)) ?? null;
}

/** Whether `path` lies in the repository. */
export function inRepo(deco: GitDecorations | null, path: string): boolean {
  if (!deco) return false;
  const key = pathKey(path, deco.caseless);
  return key.startsWith(`${deco.root}/`);
}
