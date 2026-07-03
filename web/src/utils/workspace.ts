export function normalizeWorkspaceInput(value: string): string | null {
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

export function workspaceLabel(workspace: string): string {
  const trimmed = workspace.replace(/[\\/]+$/, '')
  if (!trimmed) return workspace
  return trimmed.split(/[\\/]/).pop() || workspace
}

const CODING_WORKSPACES_KEY = 'oa-coding-workspaces'
const LAST_CODING_WORKSPACE_KEY = 'oa-last-coding-workspace'

export interface CodingWorkspaceEntry {
  id: string
  path: string
  createdAt: string
}

function workspaceId(workspace: string): string {
  let hash = 0
  for (let i = 0; i < workspace.length; i += 1) {
    hash = Math.imul(31, hash) + workspace.charCodeAt(i) | 0
  }
  return `w${(hash >>> 0).toString(36)}`
}

function parseEntries(raw: unknown): CodingWorkspaceEntry[] {
  if (!Array.isArray(raw)) return []
  return raw
    .map((item, index) => {
      const fallbackCreatedAt = new Date(index).toISOString()
      if (typeof item === 'string') return { id: workspaceId(item), path: item, createdAt: fallbackCreatedAt }
      if (item && typeof item === 'object' && 'path' in item && typeof item.path === 'string') {
        const id = 'id' in item && typeof item.id === 'string' ? item.id : workspaceId(item.path)
        const createdAt = 'createdAt' in item && typeof item.createdAt === 'string' ? item.createdAt : fallbackCreatedAt
        return { id, path: item.path, createdAt }
      }
      return null
    })
    .filter((item): item is CodingWorkspaceEntry => item !== null)
}

export function loadCodingWorkspaces(): string[] {
  return loadCodingWorkspaceEntries().map((entry) => entry.path)
}

export function loadCodingWorkspaceEntries(): CodingWorkspaceEntry[] {
  try {
    const raw = localStorage.getItem(CODING_WORKSPACES_KEY)
    return parseEntries(raw ? JSON.parse(raw) : [])
  } catch {
    return []
  }
}

export function saveCodingWorkspace(workspace: string): CodingWorkspaceEntry {
  const entries = loadCodingWorkspaceEntries()
  const existing = entries.find((item) => item.path === workspace)
  const entry = existing ?? { id: workspaceId(workspace), path: workspace, createdAt: new Date().toISOString() }
  const next = existing ? entries : [...entries, entry]
    .sort((a, b) => Date.parse(a.createdAt) - Date.parse(b.createdAt))
  try {
    localStorage.setItem(CODING_WORKSPACES_KEY, JSON.stringify(next))
    window.dispatchEvent(new CustomEvent('coding-workspaces-changed'))
  } catch {
    // ignore storage failures
  }
  return entry
}

/**
 * Removes a workspace from the saved list. Sessions belonging to it are
 * left untouched in the backend — reopening the same path later will
 * resurface them. Also clears the "last opened" pointer if it was this
 * workspace, so a stale id doesn't get auto-restored on next launch.
 */
export function removeCodingWorkspace(workspace: string): void {
  try {
    const entries = loadCodingWorkspaceEntries().filter((entry) => entry.path !== workspace)
    localStorage.setItem(CODING_WORKSPACES_KEY, JSON.stringify(entries))
    const lastId = localStorage.getItem(LAST_CODING_WORKSPACE_KEY)
    if (lastId && !entries.some((entry) => entry.id === lastId)) {
      localStorage.removeItem(LAST_CODING_WORKSPACE_KEY)
    }
    window.dispatchEvent(new CustomEvent('coding-workspaces-changed'))
  } catch {
    // ignore storage failures
  }
}

export function saveLastCodingWorkspace(workspace: string): CodingWorkspaceEntry {
  const entry = saveCodingWorkspace(workspace)
  try {
    localStorage.setItem(LAST_CODING_WORKSPACE_KEY, entry.id)
  } catch {
    // ignore storage failures
  }
  return entry
}

export function loadLastCodingWorkspace(): CodingWorkspaceEntry | null {
  try {
    const id = localStorage.getItem(LAST_CODING_WORKSPACE_KEY)
    if (!id) return null
    return loadCodingWorkspaceEntries().find((entry) => entry.id === id) ?? null
  } catch {
    return null
  }
}

export function shouldRestoreLastCodingWorkspace(
  mode: 'normal' | 'coding',
  sessionId: string | undefined,
  pathname: string,
): boolean {
  return mode === 'coding' && !sessionId && pathname === '/coding'
}

const LAST_CODING_FOCUS_KEY = 'oa-last-coding-focus'

/**
 * Like saveLastCodingWorkspace, but project-aware: a project session spans
 * every member repo, so persisting its representative repo's path (like
 * saveLastCodingWorkspace alone would) silently drops back to a single-repo
 * session next time bare /coding restores. Call this from the one place
 * that observes every coding session generically (TeamLayoutBase) instead
 * of saveLastCodingWorkspace directly.
 */
export function saveLastCodingFocus(session: {
  project_id?: string | null
  workspace?: string | null
}): void {
  if (session.project_id) {
    try {
      localStorage.setItem(LAST_CODING_FOCUS_KEY, session.project_id)
    } catch {
      // ignore storage failures
    }
    return
  }
  if (session.workspace) {
    // Keeps the existing entries-list bookkeeping (recently opened
    // workspaces, used by e.g. the scheduler's workspace picker) working
    // exactly as before, since only the *last-focus* pointer is new here.
    saveLastCodingWorkspace(session.workspace)
    try {
      localStorage.setItem(LAST_CODING_FOCUS_KEY, session.workspace)
    } catch {
      // ignore storage failures
    }
  }
}

/** The last-visited coding focus, as a /coding/$focusId-shaped string —
 * either a project id or a workspace path. Falls back to the legacy
 * workspace-only pointer for sessions saved before this key existed. */
export function loadLastCodingFocusId(): string | null {
  try {
    const focus = localStorage.getItem(LAST_CODING_FOCUS_KEY)
    if (focus) return focus
    return loadLastCodingWorkspace()?.path ?? null
  } catch {
    return null
  }
}

export function clearLastCodingFocus(focusId: string): void {
  if (!isProjectFocusId(focusId)) removeCodingWorkspace(focusId)
  try {
    if (localStorage.getItem(LAST_CODING_FOCUS_KEY) === focusId) {
      localStorage.removeItem(LAST_CODING_FOCUS_KEY)
    }
  } catch {
    // ignore storage failures
  }
}

export function workspaceFromSession(
  mode: 'normal' | 'coding',
  sessionId: string | undefined,
  sessionWorkspace: string | null | undefined,
): string | null {
  if (mode !== 'coding' || !sessionId) return null
  return sessionWorkspace ?? null
}

const PROJECT_FOCUS_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/**
 * The /coding/$focusId route segment identifying which repo/project a
 * session URL points at: a project's UUID takes priority (a project session
 * spans repos, so its own id is the only stable anchor), otherwise the
 * standalone workspace's filesystem path. Returned RAW (not URI-encoded) —
 * the router's own param serialization already percent-encodes path params
 * (including '/' and ':'), so encoding it here too would double-encode.
 * Project ids are real UUIDs and a filesystem path never is, so
 * isProjectFocusId can tell them apart on the way back in.
 */
export function codingFocusId(session: {
  project_id?: string | null
  workspace?: string | null
}): string | null {
  if (session.project_id) return session.project_id
  if (session.workspace) return session.workspace
  return null
}

export function isProjectFocusId(focusId: string): boolean {
  return PROJECT_FOCUS_ID_RE.test(focusId)
}
