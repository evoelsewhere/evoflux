/**
 * EvoFlux API client — team group: /team chat, sessions, workspace, files.
 */

import { apiBaseUrl, apiUrl } from '../base-url'
import { withTokenParam } from '../auth'
import { readSSE } from '../sse'
import type { SSECallbacks } from '../sse'
import { parseDetailOrThrow } from './_shared'
import type {
  Chapter,
  SessionDetailResponse,
  TeamSessionResolveResponse,
  SessionPageResponse,
  SessionResponse,
  TeamHistoryResponse,
  TeamAgentsResponse,
  WorkspaceValidationResponse,
  WorktreeCreateResponse,
  WorktreeInfo,
  CodingWorkspaceTreeResponse,
  WorkspaceBrowseResponse,
  WorkspaceGitDiffResponse,
  WorkspaceStatusResponse,
  TeamCommandResponse,
  WorkspaceFilesResponse,
  CodingWorkspaceFilesResponse,
  TodosResponse,
  CodingProject,
  ProjectCreateRequest,
  AddWorkspaceToProjectRequest,
  ProjectWorkspaceItem,
  CrossRepoEdge,
  CrossRepoResolveRequest,
  CrossRepoResolveJob,
  CrossRepoResolveStatusResponse,
  ProjectRepoStatus,
  ProjectReindexStartedResponse,
  ProjectCodeSearchResponse,
  ProjectCodeGraphData,
} from '../types'

export async function postTeamChat(
  message?: string | null,
  sessionId?: string | null,
  interrupt = false,
  files?: File[],
  mode = 'forge',
  workspace?: string | null,
  model?: string | null,
  thinkingLevel?: string | null,
  shell = false,
  fastMode = false,
): Promise<{ status: string; session_id: string; message_id?: string }> {
  const formData = new FormData()
  if (message) {
    formData.append('message', message)
  }
  if (sessionId) {
    formData.append('session_id', sessionId)
  }
  if (interrupt) {
    formData.append('interrupt', 'true')
  }
  if (mode !== 'forge') {
    formData.append('mode', mode)
  }
  if (workspace) {
    formData.append('workspace', workspace)
  }
  if (model !== undefined) {
    formData.append('model', model ?? '')
  }
  if (thinkingLevel !== undefined) {
    formData.append('thinking_level', thinkingLevel ?? '')
  }
  if (fastMode) {
    formData.append('fast_mode', 'true')
  }
  if (shell) {
    formData.append('shell', 'true')
  }
  if (files && files.length > 0) {
    for (const file of files) {
      formData.append('files', file)
    }
  }

  const res = await fetch(`${apiBaseUrl()}/team/chat`, {
    method: 'POST',
    headers: { Accept: 'application/json' },
    body: formData,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = Array.isArray(body?.detail)
      ? body.detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join('; ')
      : body?.detail
    throw new Error(detail || `POST /team/chat failed: ${res.status}`)
  }
  return res.json()
}

export async function postTeamCommand(
  command: 'continue' | 'compact' | 'undo' | 'redo',
  sessionId: string,
): Promise<TeamCommandResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/commands`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command, session_id: sessionId }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `POST /team/commands failed: ${res.status}`)
  }
  return res.json()
}

export function resolveApiUrl(url: string | undefined): string | undefined {
  if (!url) return url
  if (/^(https?:)?\/\//i.test(url)) return url
  if (url.startsWith('data:') || url.startsWith('blob:')) return url
  if (url.startsWith('/api/')) return withTokenParam(apiUrl(url.slice('/api'.length)))
  return url
}

export async function cancelQueuedTeamMessage(sessionId: string, messageId: string): Promise<void> {
  const res = await fetch(
    `${apiBaseUrl()}/team/sessions/${encodeURIComponent(sessionId)}/queued-messages/${encodeURIComponent(messageId)}`,
    { method: 'DELETE' },
  )
  if (res.status === 404) return
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `DELETE queued message failed: ${res.status}`)
  }
}

export async function replyPermissionRequest(
  sessionId: string,
  requestId: string,
  reply: 'once' | 'always' | 'reject',
): Promise<void> {
  const res = await fetch(
    `${apiBaseUrl()}/team/${encodeURIComponent(sessionId)}/permissions/${encodeURIComponent(requestId)}/reply`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reply }),
    },
  )
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `POST permissions reply failed: ${res.status}`)
  }
}

export async function setSessionPermissionMode(
  sessionId: string,
  mode: string,
): Promise<void> {
  const res = await fetch(
    `${apiBaseUrl()}/team/sessions/${encodeURIComponent(sessionId)}/permission-mode`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    },
  )
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `PATCH permission-mode failed: ${res.status}`)
  }
}

export async function replyPlanApproval(
  sessionId: string,
  requestId: string,
  decision: 'approved' | 'rejected' | 'revise',
  feedback?: string,
): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/${encodeURIComponent(sessionId)}/plan/reply`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id: requestId, decision, feedback: feedback ?? null }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `POST plan/reply failed: ${res.status}`)
  }
}

export async function getPendingQuestions(sessionId: string): Promise<{
  questions: Array<{
    request_id: string
    items: Array<{ question: string; options: string[] }>
  }>
}> {
  const res = await fetch(
    `${apiBaseUrl()}/team/${encodeURIComponent(sessionId)}/questions/pending`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'getPendingQuestions')
  return res.json()
}

export async function replyAskUserQuestion(
  sessionId: string,
  requestId: string,
  answers: string[],
): Promise<void> {
  const res = await fetch(
    `${apiBaseUrl()}/team/${encodeURIComponent(sessionId)}/questions/${encodeURIComponent(requestId)}/reply`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answers }),
    },
  )
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `POST questions reply failed: ${res.status}`)
  }
}

export function teamStream(sessionId: string, callbacks: SSECallbacks, signal?: AbortSignal): void {
  fetch(`${apiBaseUrl()}/team/${encodeURIComponent(sessionId)}/stream`, { signal })
    .then((res) => {
      if (!res.ok) throw new Error(`GET /team/${sessionId}/stream failed: ${res.status}`)
      readSSE(res, callbacks)
    })
    .catch((err) => { if (err.name !== 'AbortError') callbacks.onError?.(err) })
}

export async function listTeamAgents(workspace?: string | null): Promise<TeamAgentsResponse> {
  const params = new URLSearchParams()
  if (workspace) params.set('workspace', workspace)
  const query = params.toString()
  const res = await fetch(`${apiBaseUrl()}/team/agents${query ? `?${query}` : ''}`)
  if (!res.ok) await parseDetailOrThrow(res, 'listTeamAgents')
  return res.json()
}

export async function validateWorkspace(workspace: string): Promise<WorkspaceValidationResponse> {
  const params = new URLSearchParams({ workspace })
  const res = await fetch(`${apiBaseUrl()}/team/workspace/validate?${params}`)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `validateWorkspace failed: ${res.status}`)
  }
  return res.json()
}

export async function browseWorkspaces(path?: string | null): Promise<WorkspaceBrowseResponse> {
  const params = new URLSearchParams()
  if (path) params.set('path', path)
  const query = params.toString()
  const res = await fetch(`${apiBaseUrl()}/team/workspace/browse${query ? `?${query}` : ''}`)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `browseWorkspaces failed: ${res.status}`)
  }
  return res.json()
}

export async function getCodingWorkspaceTree(): Promise<CodingWorkspaceTreeResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/tree`)
  if (!res.ok) await parseDetailOrThrow(res, 'getCodingWorkspaceTree')
  return res.json()
}

export async function listWorktrees(sourceWorkspace: string): Promise<WorktreeInfo[]> {
  const params = new URLSearchParams({ source_workspace: sourceWorkspace })
  const res = await fetch(`${apiBaseUrl()}/team/workspace/worktrees?${params}`)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `listWorktrees failed: ${res.status}`)
  }
  return res.json()
}

export async function removeWorktree(sourceWorkspace: string, directory: string): Promise<{ removed: boolean }> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/worktrees`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_workspace: sourceWorkspace, directory }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'removeWorktree')
  return res.json()
}

export async function createWorktree(options: {
  sourceWorkspace: string
  name?: string | null
  branch?: string | null
  detached?: boolean
}): Promise<WorktreeCreateResponse> {
  const body: Record<string, string | boolean | null> = {
    source_workspace: options.sourceWorkspace,
  }
  if (options.name !== undefined) body.name = options.name
  if (options.branch !== undefined) body.branch = options.branch
  if (options.detached !== undefined) body.detached = options.detached
  const res = await fetch(`${apiBaseUrl()}/team/workspace/worktrees`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'createWorktree')
  return res.json()
}

export async function listCodingWorkspaceFiles(workspace: string): Promise<CodingWorkspaceFilesResponse> {
  const params = new URLSearchParams({ workspace })
  const res = await fetch(`${apiBaseUrl()}/team/workspace/files/list?${params}`)
  if (!res.ok) await parseDetailOrThrow(res, 'listCodingWorkspaceFiles')
  return res.json()
}

export async function getCodingWorkspaceGitDiff(
  workspace: string,
  paths?: string[],
): Promise<WorkspaceGitDiffResponse> {
  const params = new URLSearchParams({ workspace })
  // Repeated ``paths`` params translate to FastAPI's
  // ``Query(list[str])`` — scoped diff response covering just these
  // entries, used by the SSE cache-invalidation bridge for surgical
  // splice instead of a whole-repo refresh.
  if (paths && paths.length > 0) {
    for (const p of paths) params.append('paths', p)
  }
  const res = await fetch(`${apiBaseUrl()}/team/workspace/git-diff/view?${params}`)
  if (!res.ok) await parseDetailOrThrow(res, 'getCodingWorkspaceGitDiff')
  return res.json()
}

export async function getCodingWorkspaceStatus(workspace: string): Promise<WorkspaceStatusResponse> {
  const params = new URLSearchParams({ workspace })
  const res = await fetch(`${apiBaseUrl()}/team/workspace/status?${params}`)
  if (!res.ok) await parseDetailOrThrow(res, 'getCodingWorkspaceStatus')
  return res.json()
}

export async function listTeamSessions(
  before?: string | null,
  limit = 20,
  filters?: { mode?: 'forge' | 'coding' | 'aim'; workspace?: string | null; project_id?: string | null },
): Promise<SessionPageResponse> {
  const params = new URLSearchParams()
  if (before) params.set('before', before)
  params.set('limit', String(limit))
  if (filters?.mode) params.set('mode', filters.mode)
  if (filters?.workspace) params.set('workspace', filters.workspace)
  if (filters?.project_id) params.set('project_id', filters.project_id)
  const res = await fetch(`${apiBaseUrl()}/team/sessions?${params}`)
  if (!res.ok) await parseDetailOrThrow(res, 'listTeamSessions')
  return res.json()
}

export async function setCodingWorkspaceVisibility(workspace: string, hidden: boolean): Promise<{ workspace: string; hidden: boolean; updated: number }> {
  const res = await fetch(`${apiBaseUrl()}/team/workspace/visibility`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, hidden }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'setCodingWorkspaceVisibility')
  return res.json()
}

export async function getTeamSession(id: string): Promise<SessionDetailResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/sessions/${id}`)
  if (!res.ok) await parseDetailOrThrow(res, 'getTeamSession')
  return res.json()
}

export async function resolveTeamSession(options: {
  mode?: string
  workspace?: string | null
  project_id?: string | null
  model?: string | null
  thinkingLevel?: string | null
  create?: boolean
  worktreeFrom?: string | null
  worktreeName?: string | null
  worktreeBranch?: string | null
}): Promise<TeamSessionResolveResponse> {
  const body: Record<string, string | boolean | null> = {
    mode: options.mode ?? 'forge',
  }
  if (options.workspace !== undefined) body.workspace = options.workspace
  if (options.project_id !== undefined) body.project_id = options.project_id
  if (options.model !== undefined) body.model = options.model
  if (options.thinkingLevel !== undefined) body.thinking_level = options.thinkingLevel
  if (options.create !== undefined) body.create = options.create
  if (options.worktreeFrom !== undefined) body.worktree_from = options.worktreeFrom
  if (options.worktreeName !== undefined) body.worktree_name = options.worktreeName
  if (options.worktreeBranch !== undefined) body.worktree_branch = options.worktreeBranch
  const res = await fetch(`${apiBaseUrl()}/team/sessions/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'resolveTeamSession')
  return res.json()
}

export async function updateTeamSessionTitle(id: string, title: string): Promise<SessionResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/sessions/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'updateTeamSessionTitle')
  return res.json()
}

export async function deleteTeamSession(id: string): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/sessions/${id}`, { method: 'DELETE' })
  if (!res.ok) await parseDetailOrThrow(res, 'deleteTeamSession')
}

export async function teamHistory(sessionId: string, before?: string): Promise<TeamHistoryResponse> {
  const url = before
    ? `${apiBaseUrl()}/team/${encodeURIComponent(sessionId)}/history?before=${encodeURIComponent(before)}`
    : `${apiBaseUrl()}/team/${encodeURIComponent(sessionId)}/history`
  const res = await fetch(url)
  if (!res.ok) await parseDetailOrThrow(res, 'teamHistory')
  return res.json()
}

/**
 * List every file under the session's agent workspace (``.EvoFlux/team/{sid}``).
 *
 * Returns an empty list for fresh sessions where the workspace hasn't been
 * created yet (the agent hasn't written anything).  File bytes are fetched
 * via the ``/media/{path}`` proxy, not this endpoint — keep payloads small.
 */
export async function listWorkspaceFiles(sessionId: string): Promise<WorkspaceFilesResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/${encodeURIComponent(sessionId)}/files`)
  if (!res.ok) await parseDetailOrThrow(res, 'listWorkspaceFiles')
  return res.json()
}

export async function updateSessionWorkspace(sessionId: string, path: string | null): Promise<WorkspaceFilesResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/${encodeURIComponent(sessionId)}/workspace`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'updateSessionWorkspace')
  return res.json()
}

export async function uploadWorkspaceFiles(sessionId: string, files: File[], subfolder?: string): Promise<WorkspaceFilesResponse> {
  const fd = new FormData()
  files.forEach((f) => fd.append('files', f))
  const params = subfolder ? `?subfolder=${encodeURIComponent(subfolder)}` : ''
  const res = await fetch(`${apiBaseUrl()}/team/${encodeURIComponent(sessionId)}/files/upload${params}`, {
    method: 'POST',
    body: fd,
  })
  if (!res.ok) await parseDetailOrThrow(res, 'uploadWorkspaceFiles')
  return res.json()
}

export async function moveWorkspaceFile(sessionId: string, fromPath: string, toPath: string): Promise<WorkspaceFilesResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/${encodeURIComponent(sessionId)}/files/move`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ from_path: fromPath, to_path: toPath }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'moveWorkspaceFile')
  return res.json()
}

export async function deleteWorkspaceFile(sessionId: string, filePath: string): Promise<WorkspaceFilesResponse> {
  const encoded = filePath.split('/').map(encodeURIComponent).join('/')
  const res = await fetch(`${apiBaseUrl()}/team/${encodeURIComponent(sessionId)}/files/${encoded}`, {
    method: 'DELETE',
  })
  if (!res.ok) await parseDetailOrThrow(res, 'deleteWorkspaceFile')
  return res.json()
}

/** Build the ``/media/{path}`` URL for a workspace file.
 *
 *  Each segment is encoded individually — ``encodeURIComponent`` on the whole
 *  path would escape the ``/`` separators that the ``{path:path}`` route
 *  pattern needs to see.
 */
export function workspaceMediaUrl(sessionId: string, path: string, options?: { download?: boolean }): string {
  const encoded = path.split('/').map(encodeURIComponent).join('/')
  const url = apiUrl(`/team/${encodeURIComponent(sessionId)}/media/${encoded}`)
  if (!options?.download) return withTokenParam(url)
  const separator = url.includes('?') ? '&' : '?'
  return withTokenParam(`${url}${separator}download=1`)
}

/** Build the URL for serving a raw file from a *coding* workspace (not a
 *  session workspace).  Hits ``GET /api/team/workspace/files/read``.
 *
 *  Each segment is encoded individually so ``/`` separators survive and
 *  path-traversal sequences (``../``) are rejected by the server.
 */
export function codingWorkspaceFileUrl(workspace: string, path: string, options?: { download?: boolean }): string {
  const params = new URLSearchParams({ workspace, path })
  if (options?.download) params.set('download', '1')
  return withTokenParam(apiUrl(`/team/workspace/files/read?${params}`))
}

/** Write file content to the coding workspace via PUT. */
export async function writeCodingWorkspaceFile(workspace: string, path: string, content: string): Promise<void> {
  const params = new URLSearchParams({ workspace, path })
  const res = await fetch(apiUrl(`/team/workspace/files/write?${params}`), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'writeCodingWorkspaceFile')
}

export async function getTodos(sessionId: string): Promise<TodosResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/sessions/${encodeURIComponent(sessionId)}/todos`)
  if (!res.ok) await parseDetailOrThrow(res, 'getTodos')
  return res.json()
}

export interface BrowserTabInfo {
  index: number
  url: string
  title: string
}

export interface BrowserSessionResponse {
  active: boolean
  cdp_url: string | null
  cdp_http: string | null
  current_url: string | null
  current_title: string | null
  tabs: BrowserTabInfo[]
}

export async function getBrowserSession(sessionId: string): Promise<BrowserSessionResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/${encodeURIComponent(sessionId)}/browser`)
  if (!res.ok) await parseDetailOrThrow(res, 'getBrowserSession')
  return res.json()
}

// ── Session chapters ──────────────────────────────────────────────────────────

export async function listSessionChapters(sessionId: string): Promise<Chapter[]> {
  const res = await fetch(
    `${apiBaseUrl()}/team/sessions/${encodeURIComponent(sessionId)}/chapters`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'listSessionChapters')
  return res.json()
}

export async function createSessionChapter(
  sessionId: string,
  title: string,
  summary?: string | null,
  messageId?: string | null,
): Promise<Chapter> {
  const res = await fetch(
    `${apiBaseUrl()}/team/sessions/${encodeURIComponent(sessionId)}/chapters`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, summary: summary ?? null, message_id: messageId ?? null }),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'createSessionChapter')
  return res.json()
}

export async function deleteSessionChapter(
  sessionId: string,
  chapterId: string,
): Promise<void> {
  const res = await fetch(
    `${apiBaseUrl()}/team/sessions/${encodeURIComponent(sessionId)}/chapters/${encodeURIComponent(chapterId)}`,
    { method: 'DELETE' },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'deleteSessionChapter')
}

// ── Coding Projects API ───────────────────────────────────────────────────────
// Note: there's no listProjects() here — the coding sidebar gets the full
// projects list bundled into getCodingWorkspaceTree()'s response instead
// (see CodingWorkspaceTreeResponse.projects), so it never has to reconcile
// two independently-fetched lists. GET /team/projects itself still exists
// backend-side for any other consumer that just wants the bare list.

export async function getProject(id: string): Promise<CodingProject> {
  const res = await fetch(`${apiBaseUrl()}/team/projects/${encodeURIComponent(id)}`)
  if (!res.ok) await parseDetailOrThrow(res, 'getProject')
  return res.json()
}

export async function createProject(body: ProjectCreateRequest): Promise<CodingProject> {
  const res = await fetch(`${apiBaseUrl()}/team/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'createProject')
  return res.json()
}

export async function updateProject(
  id: string,
  body: Partial<{ name: string; description: string; settings: Record<string, unknown> }>,
): Promise<CodingProject> {
  const res = await fetch(`${apiBaseUrl()}/team/projects/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'updateProject')
  return res.json()
}

export async function deleteProject(id: string): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/projects/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
  if (!res.ok) await parseDetailOrThrow(res, 'deleteProject')
}

export async function addWorkspaceToProject(
  projectId: string,
  body: AddWorkspaceToProjectRequest,
): Promise<ProjectWorkspaceItem> {
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/workspaces`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'addWorkspaceToProject')
  return res.json()
}

export async function removeWorkspaceFromProject(
  projectId: string,
  workspaceId: string,
): Promise<void> {
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/workspaces/${encodeURIComponent(workspaceId)}`,
    { method: 'DELETE' },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'removeWorkspaceFromProject')
}

export async function updateWorkspaceInProject(
  projectId: string,
  workspaceId: string,
  body: Partial<{ display_name: string; sort_order: number }>,
): Promise<ProjectWorkspaceItem> {
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/workspaces/${encodeURIComponent(workspaceId)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'updateWorkspaceInProject')
  return res.json()
}

export async function listCrossRepoEdges(
  projectId: string,
  status?: 'unresolved' | 'resolved' | 'rejected',
): Promise<CrossRepoEdge[]> {
  const params = status ? `?status=${encodeURIComponent(status)}` : ''
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/cross-repo/edges${params}`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'listCrossRepoEdges')
  return res.json()
}

// Returns a job snapshot — the backend always runs Tier 0 + Tier A +
// lexical Tier B as a background job. Poll getCrossRepoResolveStatus for
// the job's progress.
export async function startCrossRepoResolve(
  projectId: string,
  body: CrossRepoResolveRequest = {},
): Promise<CrossRepoResolveJob> {
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/cross-repo/resolve`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'startCrossRepoResolve')
  return res.json()
}

export async function getCrossRepoResolveStatus(
  projectId: string,
): Promise<CrossRepoResolveStatusResponse> {
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/cross-repo/status`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'getCrossRepoResolveStatus')
  return res.json()
}

// Single entry point for the Graph tab's index/reindex button: starts every
// repo's index job in one call, and (multi-repo projects) auto-chains into
// cross-repo resolve server-side once they all finish — no per-repo looping
// or client-side "wait then resolve" chaining needed.
export async function reindexProjectCodeGraph(
  projectId: string,
  options?: { full?: boolean; languages?: string[] },
): Promise<ProjectReindexStartedResponse> {
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/code-graph/reindex`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        full: options?.full ?? false,
        languages: options?.languages ?? null,
      }),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'reindexProjectCodeGraph')
  return res.json()
}

export async function getProjectCodeGraphStatus(
  projectId: string,
): Promise<ProjectRepoStatus[]> {
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/code-graph/status`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'getProjectCodeGraphStatus')
  return res.json()
}

export async function searchProjectCodeGraph(
  projectId: string,
  query: string,
  options?: { kind?: string; limitPerRepo?: number },
): Promise<ProjectCodeSearchResponse> {
  const params = new URLSearchParams({ query })
  if (options?.kind) params.set('kind', options.kind)
  if (options?.limitPerRepo) params.set('limit_per_repo', String(options.limitPerRepo))
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/code-graph/search?${params}`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'searchProjectCodeGraph')
  return res.json()
}

export async function getProjectCodeGraphData(
  projectId: string,
  options?: { nodeLimitPerRepo?: number; edgeLimitPerRepo?: number },
): Promise<ProjectCodeGraphData> {
  const params = new URLSearchParams()
  if (options?.nodeLimitPerRepo !== undefined) {
    params.set('node_limit_per_repo', String(options.nodeLimitPerRepo))
  }
  if (options?.edgeLimitPerRepo !== undefined) {
    params.set('edge_limit_per_repo', String(options.edgeLimitPerRepo))
  }
  const qs = params.toString()
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/code-graph/graph-data${qs ? `?${qs}` : ''}`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'getProjectCodeGraphData')
  return res.json()
}
