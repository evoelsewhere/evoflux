// IPC to the shell's file commands (src-tauri/src/files.rs). No React.

import { invoke } from "@tauri-apps/api/core";

export interface DirEntry {
  name: string;
  path: string;
  dir: boolean;
  size: number;
  /** Build output, dependencies, hidden files. */
  dimmed: boolean;
}

export type FileContent =
  | { kind: "text"; text: string; size: number; mtime: number; lossy: boolean }
  | { kind: "image"; dataUrl: string; size: number; mtime: number }
  | { kind: "binary"; size: number; mtime: number }
  | { kind: "tooLarge"; size: number; mtime: number };

export interface FileStat {
  exists: boolean;
  dir: boolean;
  size: number;
  mtime: number;
}

export interface SearchHit {
  path: string;
  relative: string;
  score: number;
}

export interface GrepHit {
  path: string;
  relative: string;
  /** 1-based. */
  line: number;
  /** 1-based. */
  column: number;
  /** The line, trimmed and cut around the match. */
  preview: string;
}

export const listDir = (path: string) => invoke<DirEntry[]>("fs_list_dir", { path });
export const statFile = (path: string) => invoke<FileStat>("fs_stat", { path });
export const readFile = (path: string) => invoke<FileContent>("fs_read_file", { path });
/** Resolves to the new mtime; rejects with `conflict: …` when the file changed since `expectedMtime`. */
export const writeFile = (path: string, text: string, expectedMtime?: number) =>
  invoke<number>("fs_write_file", { path, text, expectedMtime: expectedMtime ?? null });
export const searchFiles = (root: string, query: string, limit = 60) =>
  invoke<SearchHit[]>("fs_search", { root, query, limit });
/** Lines containing `query` (case-insensitive) in the text files under `root`. */
export const grepFiles = (root: string, query: string, limit = 300) =>
  invoke<GrepHit[]>("fs_grep", { root, query, limit });

export const isConflict = (error: unknown) => String(error).includes("conflict:");

const SEP = /[\\/]/;
export const fileName = (path: string) => path.split(SEP).filter(Boolean).pop() ?? path;
export const parentDir = (path: string) => path.replace(/[\\/][^\\/]*[\\/]?$/, "") || path;

/** `path` relative to `root` with forward slashes, or `path` itself when outside it. */
export function relativePath(root: string, path: string): string {
  const norm = (p: string) => p.replace(/\\/g, "/").replace(/\/+$/, "");
  const r = norm(root);
  const p = norm(path);
  const caseless = /^[a-z]:/i.test(r);
  const starts = caseless ? p.toLowerCase().startsWith(`${r.toLowerCase()}/`) : p.startsWith(`${r}/`);
  return starts ? p.slice(r.length + 1) : p;
}

/** Same file, whatever the slashes or (on Windows) the case. */
export function samePath(a: string, b: string): boolean {
  const norm = (p: string) => p.replace(/\\/g, "/").replace(/\/+$/, "");
  const x = norm(a);
  const y = norm(b);
  return /^[a-z]:/i.test(x) ? x.toLowerCase() === y.toLowerCase() : x === y;
}

/** Join a path found in text (relative or absolute) to `root`. */
export function resolvePath(root: string, path: string): string {
  if (/^([a-z]:[\\/]|[\\/]|~)/i.test(path)) return path;
  const sep = root.includes("\\") ? "\\" : "/";
  return `${root.replace(/[\\/]+$/, "")}${sep}${path.replace(/^\.[\\/]/, "").replace(/[\\/]/g, sep)}`;
}
