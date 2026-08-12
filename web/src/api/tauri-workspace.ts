/**
 * Tauri-native workspace file operations.
 *
 * When running inside the Tauri desktop shell, file listing and reading
 * bypass the Python HTTP sidecar entirely — Rust handles the filesystem
 * I/O directly, which is faster and more reliable.
 *
 * Falls back gracefully to HTTP API when Tauri is not available (web browser).
 */
import { getPlatform } from '@/hooks/use-platform'
import type { WorkspaceFilesResponse, WorkspaceFileInfo } from './types'

interface TauriWorkspaceFileEntry {
  path: string
  name: string
  size: number
  mtime: number
  mime: string
}

interface TauriWorkspaceFilesResult {
  session_id: string
  files: TauriWorkspaceFileEntry[]
  truncated: boolean
  workspace_root: string
}

/** Check if Tauri IPC is available at runtime. */
export function isTauriAvailable(): boolean {
  return getPlatform().isTauri
}

async function tauriInvoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import('@tauri-apps/api/core')
  return invoke<T>(cmd, args)
}

/** Decode a base64 payload containing UTF-8 text. */
export function decodeBase64Utf8(base64: string): string {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i)
  }
  return new TextDecoder('utf-8').decode(bytes)
}

/**
 * List workspace files using native Rust filesystem access.
 *
 * @param root - Absolute path to the workspace root directory.
 * @param sessionId - The session ID for the response payload.
 * @returns Workspace file listing compatible with the existing API shape.
 */
export async function tauriListWorkspaceFiles(
  root: string,
  sessionId: string,
): Promise<WorkspaceFilesResponse> {
  const result = await tauriInvoke<TauriWorkspaceFilesResult>('list_workspace_files', {
    root,
    sessionId,
  })

  // Map Rust response to the existing TypeScript interface.
  const files: WorkspaceFileInfo[] = result.files.map((f) => ({
    path: f.path,
    name: f.name,
    size: f.size,
    mtime: f.mtime,
    mime: f.mime,
  }))

  return {
    session_id: result.session_id,
    files,
    truncated: result.truncated,
    workspace_root: result.workspace_root,
  }
}

/**
 * Read a single workspace file as a base64 string using native Rust I/O.
 *
 * @param root - Absolute path to the workspace root directory.
 * @param path - POSIX-relative path within the workspace.
 * @returns Base64-encoded file content.
 */
export async function tauriReadWorkspaceFile(root: string, path: string): Promise<string> {
  return tauriInvoke<string>('read_workspace_file', { root, path })
}

/**
 * Build a data URL from a Tauri-read workspace file.
 *
 * @param root - Absolute path to the workspace root directory.
 * @param path - POSIX-relative path within the workspace.
 * @param mimeType - MIME type of the file (for the data URL header).
 * @returns A `data:{mime};base64,...` URL ready for use in `<img src>` etc.
 */
export async function tauriWorkspaceFileDataUrl(
  root: string,
  path: string,
  mimeType: string,
): Promise<string> {
  const b64 = await tauriReadWorkspaceFile(root, path)
  return `data:${mimeType};base64,${b64}`
}

/**
 * Open a workspace file with the system's default application.
 *
 * Uses the OS default app for the file type (e.g. Excel for .xlsx,
 * Preview for .png, VS Code for .py).
 *
 * @param root - Absolute path to the workspace root directory.
 * @param path - POSIX-relative path within the workspace.
 */
export async function tauriOpenWorkspaceFile(root: string, path: string): Promise<void> {
  return tauriInvoke<void>('open_workspace_file_with_handle', { root, path })
}

/** Open the workspace root in Finder / File Explorer. */
export async function tauriOpenWorkspaceRoot(root: string): Promise<void> {
  return tauriInvoke<void>('open_workspace_root_with_handle', { root })
}

/** Reveal a workspace file, or the root folder when path is omitted. */
export async function tauriRevealWorkspacePath(root: string, path?: string): Promise<void> {
  return tauriInvoke<void>('reveal_workspace_path_with_handle', {
    root,
    path: path ?? null,
  })
}

// ── "Open with" ─────────────────────────────────────────────────────────────

/** A desktop app that can open the workspace root. */
export interface WorkspaceOpener {
  /** Stable identifier passed to tauriOpenWorkspaceWith. */
  id: string
  /** Display name shown in the menu. */
  name: string
  /** Category — drives fallback presentation and menu ordering. */
  kind: 'editor' | 'file_manager' | 'terminal'
  /** PNG data URL extracted from the installed app by the native shell. */
  icon_data_url: string | null
}

/**
 * List desktop apps available to open the workspace root.
 *
 * Detection happens in Rust against a curated catalog (editors, file
 * managers, terminals) — only apps actually installed are returned.
 */
export async function tauriListWorkspaceOpeners(): Promise<WorkspaceOpener[]> {
  return tauriInvoke<WorkspaceOpener[]>('list_workspace_openers')
}

/**
 * Open the workspace root with a specific app from the opener catalog.
 *
 * @param root - Absolute path to the workspace root directory.
 * @param openerId - An `id` returned by tauriListWorkspaceOpeners.
 */
export async function tauriOpenWorkspaceWith(root: string, openerId: string): Promise<void> {
  return tauriInvoke<void>('open_workspace_with', { root, openerId })
}

/** A single directory entry from list_directory. */
export interface DirEntry {
  name: string
  path: string
  is_dir: boolean
  size: number
  mtime: number
  mime: string
}

/** Response from list_directory. */
export interface DirListingResult {
  path: string
  parent: string | null
  entries: DirEntry[]
}

/**
 * List immediate children of a directory (lazy loading).
 *
 * Unlike tauriListWorkspaceFiles which recursively walks the entire tree,
 * this only lists the immediate children. Directories are expanded on-demand.
 *
 * @param root - Absolute path to the workspace root directory.
 * @param path - POSIX-relative path within the workspace (empty string for root).
 * @returns Directory listing with entries sorted: dirs first, then alphabetically.
 */
export async function tauriListDirectory(root: string, path: string): Promise<DirListingResult> {
  return tauriInvoke<DirListingResult>('list_directory', { root, path })
}

// ── Native File Watcher ──────────────────────────────────────────────────────

/** A file change event from the native watcher. */
export interface FileChangeEvent {
  change_type: 'added' | 'modified' | 'deleted'
  path: string
}

/**
 * Start watching a workspace directory for file changes.
 *
 * Emits `file-change` events via Tauri's event system.
 * Events are debounced (50ms) and filtered (skips .git, node_modules, etc.).
 *
 * @param root - Absolute path to the workspace root directory.
 */
export async function tauriStartFileWatcher(root: string): Promise<void> {
  return tauriInvoke<void>('start_file_watcher', { root })
}

/**
 * Stop watching a workspace directory.
 *
 * @param root - Absolute path to the workspace root directory.
 */
export async function tauriStopFileWatcher(root: string): Promise<void> {
  return tauriInvoke<void>('stop_file_watcher', { root })
}

/**
 * Listen for file change events from the native watcher.
 *
 * @param callback - Called with an array of FileChangeEvent when files change.
 * @returns Unlisten function to stop listening.
 */
export function tauriOnFileChange(callback: (events: FileChangeEvent[]) => void): () => void {
  // Dynamic import to avoid issues in non-Tauri environments
  let unlisten: (() => void) | null = null

  import('@tauri-apps/api/event').then(({ listen }) => {
    listen<FileChangeEvent[]>('file-change', (event) => {
      callback(event.payload)
    }).then((fn) => {
      unlisten = fn
    })
  })

  return () => {
    unlisten?.()
  }
}
