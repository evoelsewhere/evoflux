/**
 * Import API client — communicates with the backend import endpoints.
 *
 * Uses Tauri dialog for local file/folder selection (no web upload).
 */

import { IMPORT_SOURCE_LABELS } from '@/lib/import-source'
import { apiUrl } from '@/api/base-url'
import type { ImportSource } from '@/lib/import-source'
export type { ImportSource } from '@/lib/import-source'

// ── Types ───────────────────────────────────────────────────────────────────

export const IMPORT_ITEM_KIND_OPTIONS = [
  { kind: 'session', label: 'Conversations', description: 'Chat history' },
  { kind: 'agent', label: 'Agents', description: 'Custom agent setups' },
  { kind: 'skill', label: 'Skills', description: 'Reusable instructions' },
  { kind: 'knowledge', label: 'Knowledge', description: 'Notes and reference files' },
  { kind: 'mcp_server', label: 'MCP servers', description: 'Server configurations' },
] as const

export type ImportItemKind = (typeof IMPORT_ITEM_KIND_OPTIONS)[number]['kind']

export interface ImportItemPreview {
  id: string
  kind: string
  label: string
  preview: string
  action: 'import' | 'skip' | 'replace' | 'reimport' | 'rename'
  conflicts: string[]
  target_name: string
}

export interface DetectResponse {
  import_id: string
  detected_source: string
  path: string
  summary: Record<string, number>
  items: ImportItemPreview[]
  warnings: string[]
}

export interface ExecuteResponse {
  imported: Record<string, number>
  skipped: Record<string, number>
  errors: { item: string; kind: string; error: string }[]
  import_id?: string
}

export type ImportItemAction = 'import' | 'skip' | 'reimport'

export interface ImportItemOutcome {
  source_item_id: string
  kind: string
  label: string
  operation: string
  outcome: string
  reason?: string | null
}

export interface ImportJobDetail {
  import_id: string
  origin: 'manual' | 'auto_sync'
  undo_state: 'available' | 'unavailable' | 'undone' | 'partially_undone'
  items: ImportItemOutcome[]
}

export interface ImportUndoResponse {
  import_id: string
  state: 'available' | 'unavailable' | 'undone' | 'partially_undone'
  undone: number
  skipped: number
  items: ImportItemOutcome[]
}

// ── Source metadata ─────────────────────────────────────────────────────────

export const SOURCE_LABELS: Record<ImportSource, string> = IMPORT_SOURCE_LABELS

export const SOURCE_ICONS: Record<ImportSource, string> = {
  claude_web: 'Bot',
  claude_code: 'Terminal',
  chatgpt: 'MessageSquare',
  codex: 'Code',
  cursor: 'MousePointer',
  generic: 'FileImport',
}

/** Whether the source expects a directory picker (vs single file). */
export const DIRECTORY_SOURCES: ImportSource[] = ['claude_code', 'codex', 'cursor']

/** File filters for Tauri dialog per source. */
export const SOURCE_FILTERS: Record<ImportSource, { name: string; extensions: string[] }[]> = {
  claude_web: [{ name: 'Claude Export', extensions: ['json', 'zip'] }],
  claude_code: [], // directory picker
  chatgpt: [{ name: 'ChatGPT Export', extensions: ['zip', 'json'] }],
  codex: [], // directory picker
  cursor: [], // directory picker
  generic: [{ name: 'All Supported', extensions: ['json', 'md', 'yaml', 'yml', 'jsonl'] }],
}

// ── Tauri dialog integration ────────────────────────────────────────────────

/**
 * Open a Tauri file/folder picker for the given source type.
 * Returns the selected path string, or null if cancelled.
 *
 * Falls back to a manual prompt input if the Tauri dialog is unavailable
 * (e.g. running in a browser without Tauri).
 */
export async function pickImportSource(source: ImportSource): Promise<string | null> {
  const isDir = DIRECTORY_SOURCES.includes(source)

  try {
    // Dynamic import — works in Tauri, falls back gracefully in browser
    const { open } = await import('@tauri-apps/plugin-dialog')

    const selected = (await open({
      directory: isDir,
      multiple: false,
      filters: isDir ? undefined : SOURCE_FILTERS[source],
      title: `Select ${SOURCE_LABELS[source]} export`,
    })) as string | string[] | null

    if (typeof selected === 'string') return selected
    if (Array.isArray(selected) && (selected as string[]).length > 0)
      return (selected as string[])[0]
    return null
  } catch {
    // Tauri dialog not available — fallback to prompt
    const hint = isDir ? 'directory path' : 'file path'
    const input = window.prompt(`Enter the ${hint} for ${SOURCE_LABELS[source]} export:`)
    return input?.trim() || null
  }
}

// ── API calls ───────────────────────────────────────────────────────────────

const API_BASE = '/import'

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(`${API_BASE}${path}`), {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    const detail = body.detail
    const message =
      typeof detail === 'string'
        ? detail
        : typeof detail === 'object' && detail !== null
          ? detail.error || detail.message || JSON.stringify(detail)
          : `Import API error ${res.status}`
    throw new Error(message)
  }
  return res.json()
}

/** Detect source format from a local path. */
export async function detectImport(
  path: string,
  source?: ImportSource,
  signal?: AbortSignal,
): Promise<DetectResponse> {
  return apiFetch<DetectResponse>('/detect', {
    method: 'POST',
    body: JSON.stringify({ path, source: source ?? null }),
    signal,
  })
}

/** Get the current preview for a previously detected import. */
export async function getPreview(importId: string): Promise<DetectResponse> {
  return apiFetch<DetectResponse>(`/preview/${importId}`)
}

/** Update the conflict resolution action for a specific item. */
export async function updateItemAction(
  importId: string,
  itemIndex: number,
  action: ImportItemAction,
  signal?: AbortSignal,
): Promise<void> {
  await apiFetch(`/preview/${importId}/items/${itemIndex}`, {
    method: 'PATCH',
    body: JSON.stringify({ action }),
    signal,
  })
}

export async function updateItemsAction(
  importId: string,
  indexes: number[],
  action: ImportItemAction,
  signal?: AbortSignal,
): Promise<void> {
  await apiFetch(`/preview/${importId}/items`, {
    method: 'PATCH',
    body: JSON.stringify({ indexes, action }),
    signal,
  })
}

/** Execute the import. */
export async function executeImport(
  importId: string,
  options: { origin?: 'manual' | 'auto_sync'; signal?: AbortSignal } = {},
): Promise<ExecuteResponse> {
  return apiFetch<ExecuteResponse>(`/execute/${importId}`, {
    method: 'POST',
    body: JSON.stringify({ origin: options.origin ?? 'manual' }),
    signal: options.signal,
  })
}

/** Cancel and clean up a pending import. */
export async function cancelImport(importId: string): Promise<void> {
  await apiFetch(`/${importId}`, { method: 'DELETE' })
}

/** Scan local machine for common AI tool data locations. */
export async function scanLocalSources(signal?: AbortSignal): Promise<{ discovered: ScanResult[] }> {
  return apiFetch('/scan', { signal })
}

export interface ScanResult {
  source: string
  path: string
  label: string
  description: string
  estimated_items: number
}

/** Get auto-sync settings. */
export async function getAutoSyncSettings(signal?: AbortSignal): Promise<AutoSyncSettings> {
  return apiFetch('/auto-sync', { signal })
}

/** Update auto-sync settings. */
export async function updateAutoSyncSettings(
  settings: Partial<AutoSyncSettings>,
): Promise<AutoSyncSettings> {
  return apiFetch('/auto-sync', {
    method: 'PUT',
    body: JSON.stringify(settings),
  })
}

export interface AutoSyncSettings {
  enabled: boolean
  scan_interval_seconds: number
  notify_new_items: boolean
}

/** Fetch import history. */
export async function getImportHistory(): Promise<{ imports: HistoryEntry[] }> {
  return apiFetch('/history')
}

export async function getImportJob(jobId: string): Promise<ImportJobDetail> {
  return apiFetch(`/history/${jobId}`)
}

export async function undoImport(jobId: string): Promise<ImportUndoResponse> {
  return apiFetch(`/history/${jobId}/undo`, { method: 'POST' })
}

export interface HistoryEntry {
  import_id: string
  source: string
  path: string
  detected_format: string
  status: string
  imported: Record<string, number>
  skipped: Record<string, number>
  error_count: number
  item_count: number
  origin?: 'manual' | 'auto_sync'
  undo_state?: 'available' | 'unavailable' | 'undone' | 'partially_undone'
  undo_available?: boolean
  undoable_count?: number
  undone_count?: number
  undo_skipped_count?: number
  created_at: string | null
  completed_at: string | null
}
