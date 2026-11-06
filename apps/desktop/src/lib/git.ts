// The working folder's repository, read-only (src-tauri/src/worktrees.rs →
// `evo_worktrees`): branch, upstream, what changed against HEAD, ignored
// paths and a file's committed text. Nothing here writes to the repository.

import { invoke } from "@tauri-apps/api/core";
import type { FileChange } from "./worktrees";

export interface RepoStatus {
  /** The repository's top folder; `files` paths are relative to it. */
  root: string;
  /** `null` on a detached HEAD. */
  branch: string | null;
  /** Short commit id; `null` before the first commit. */
  head: string | null;
  upstream: string | null;
  ahead: number;
  behind: number;
  /** Staged, unstaged and new files together. */
  files: FileChange[];
  added: number;
  removed: number;
}

export const git = {
  /** `null` outside a repository. */
  status: (cwd: string) => invoke<RepoStatus | null>("git_status", { cwd }),
  /**
   * Paths git ignores in `cwd`'s repository: absolute, forward slashes, a
   * folder ends with `/` (its contents are not listed). `null` outside a repository.
   */
  ignored: (cwd: string) => invoke<string[] | null>("git_ignored", { cwd }),
  /** `path` as committed at HEAD; `null` when untracked, binary, over 1 MB or outside the repository. */
  fileBase: (cwd: string, path: string) => invoke<string | null>("git_file_base", { cwd, path }),
};
