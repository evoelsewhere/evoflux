import { STORAGE_KEYS } from '@/lib/storage-keys'

export function normalizeWorkspaceInput(value: string): string | null {
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

const WORKSPACE_UNAVAILABLE_PREFIX = 'Workspace does not exist or is not a directory:'

/**
 * Distinguish a stale/moved local workspace from an actual backend outage.
 * API helpers surface FastAPI's ``detail`` as an Error message, so keeping
 * this check here lets route recovery avoid turning a filesystem problem
 * into the global "Backend connection failed" blocker.
 */
export function isWorkspaceUnavailableError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error)
  return message.trimStart().startsWith(WORKSPACE_UNAVAILABLE_PREFIX)
}

export function workspaceLabel(workspace: string): string {
  const trimmed = workspace.replace(/[\\/]+$/, '')
  if (!trimmed) return workspace
  return trimmed.split(/[\\/]/).pop() || workspace
}

/**
 * Ask the coding sidebar to re-read its projects snapshot.
 *
 * The sidebar listens for this instead of being invalidated directly so a
 * caller does not need a QueryClient, and so the refresh still happens while
 * route navigation has briefly made the sidebar's own query inactive.
 */
export function notifyCodingWorkspacesChanged(): void {
  window.dispatchEvent(new CustomEvent('coding-workspaces-changed'))
}

const LAST_CODING_FOCUS_KEY = STORAGE_KEYS.coding.lastFocus

/**
 * Remember the project the user was last in, so bare /coding can reopen it.
 * Coding is project-only: a session without a project is never remembered.
 */
export function saveLastCodingFocus(session: { project_id?: string | null }): void {
  if (!session.project_id) return
  try {
    localStorage.setItem(LAST_CODING_FOCUS_KEY, session.project_id)
  } catch {
    // ignore storage failures
  }
}

/** The last-visited coding project id, as a /coding/$focusId segment. A
 * folder path left behind by the standalone workspaces EvoFlux used to have
 * is dropped rather than restored. */
export function loadLastCodingFocusId(): string | null {
  try {
    const focus = localStorage.getItem(LAST_CODING_FOCUS_KEY)
    if (!focus) return null
    if (isProjectFocusId(focus)) return focus
    localStorage.removeItem(LAST_CODING_FOCUS_KEY)
    return null
  } catch {
    return null
  }
}

export function clearLastCodingFocus(projectId: string): void {
  try {
    if (localStorage.getItem(LAST_CODING_FOCUS_KEY) === projectId) {
      localStorage.removeItem(LAST_CODING_FOCUS_KEY)
    }
  } catch {
    // ignore storage failures
  }
}

export function workspaceFromSession(
  mode: 'work' | 'coding',
  sessionId: string | undefined,
  sessionWorkspace: string | null | undefined,
): string | null {
  if (mode !== 'coding' || !sessionId) return null
  return sessionWorkspace ?? null
}

const PROJECT_FOCUS_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/**
 * The /coding/$focusId route segment for a session: its project's id. Every
 * Coding session belongs to a project, whose id is the only stable anchor —
 * a project session spans all of its repos.
 */
export function codingFocusId(session: { project_id?: string | null }): string | null {
  return session.project_id ?? null
}

/** Whether a /coding/$focusId segment is a project id (and not, say, a
 * folder path from an old bookmark). */
export function isProjectFocusId(focusId: string): boolean {
  return PROJECT_FOCUS_ID_RE.test(focusId)
}
