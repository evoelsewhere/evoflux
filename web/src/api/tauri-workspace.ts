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
