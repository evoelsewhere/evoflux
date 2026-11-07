// Managed Git worktrees (src-tauri/src/worktrees.rs, crates/evo-worktrees):
// where a subagent or nested session worked in isolation, and what to do
// with its changes.

import { invoke } from "@tauri-apps/api/core";

export interface WorktreeInfo {
  path: string;
  branch: string;
  location: "repository" | "userData";
  /** Uncommitted changes, or commits beyond where it started. */
  changed: boolean;
}

export interface FileChange {
  path: string;
  status: "added" | "modified" | "deleted";
  added: number | null;
  removed: number | null;
}

export interface WorktreeChanges {
  base: string;
  files: FileChange[];
  added: number;
  removed: number;
  patch: string;
  truncated: boolean;
}

export const worktrees = {
  /** A new worktree of `cwd`'s repository (Settings → Sandbox picks where). */
  create: (cwd: string) => invoke<{ path: string; branch: string; cwd: string; base: string }>("worktree_create", { cwd }),
  list: (cwd: string) => invoke<WorktreeInfo[]>("worktree_list", { cwd }),
  changes: (cwd: string, path: string) => invoke<WorktreeChanges>("worktree_changes", { cwd, path }),
  /** Bring the changes into the workspace (uncommitted) and remove the worktree. */
  apply: (cwd: string, path: string) =>
    invoke<{ files: number; added: number; removed: number }>("worktree_apply", { cwd, path }),
  discard: (cwd: string, path: string) => invoke<void>("worktree_discard", { cwd, path }),
};
