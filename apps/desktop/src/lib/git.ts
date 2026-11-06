// The working folder's repository, read-only (src-tauri/src/worktrees.rs →
// `evo_worktrees::repo_status`): branch, upstream, and what changed against HEAD.

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
};
