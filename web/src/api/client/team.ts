/**
 * EvoFlux API client — team group: /team chat, sessions, workspace, files.
 */

import { apiBaseUrl, apiUrl } from '../base-url'
import { withTokenParam } from '../auth'
import { readSSE } from '../sse'
import type { SSECallbacks } from '../sse'
import { parseDetailOrThrow } from './_shared'
import type {
  MessageResponse,
  SessionDetailResponse,
  TeamSessionResolveResponse,
  SessionFolder,
  SessionFolderListResponse,
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
  WorkspaceRootResponse,
  CodingWorkspaceFilesResponse,
  CodingDiagnosticsResponse,
  TodosResponse,
  CodingProject,
  ProjectCreateRequest,
  AddWorkspaceToProjectRequest,
  ProjectWorkspaceItem,
  CrossRepoEdge,
  ProjectRepoStatus,
  ProjectReindexStartedResponse,
  ProjectCodeSearchResponse,
  ProjectCodeGraphData,
  WebBridgeStatusResponse,
  WebBridgeLaunchBrowserResponse,
  WebBridgeAuditResponse,
  WebBridgeTeachDraft,
  WebBridgeTeachDraftReplayResponse,
  GoalResponse,
  ProcessListResponse,
} from '../types'

export async function getProcesses(): Promise<ProcessListResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/processes`, {
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) await parseDetailOrThrow(res, 'getProcesses')
  return res.json()
}

export async function terminateProcess(processId: string): Promise<void> {
  const res = await fetch(
    `${apiBaseUrl()}/team/processes/${encodeURIComponent(processId)}`,
    { method: 'DELETE' },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'terminateProcess')
}

export async function postTeamChat(
  message?: string | null,
  sessionId?: string | null,
  interrupt = false,
  files?: File[],
  mode = 'work',
  workspace?: string | null,
  model?: string | null,
  thinkingLevel?: string | null,
  shell = false,
  fastMode = false,
  webBridgeEnabled?: boolean,
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
  if (mode !== 'work') {
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
  if (webBridgeEnabled !== undefined) {
    formData.append('webbridge_enabled', String(webBridgeEnabled))
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

export async function getTeamGoal(sessionId: string): Promise<GoalResponse | null> {
  const res = await fetch(`${apiBaseUrl()}/team/${encodeURIComponent(sessionId)}/goal`)
  if (!res.ok) await parseDetailOrThrow(res, `GET /team/${sessionId}/goal`)
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
    /** Owning agent session when present — prefer for reply POSTs. */
    session_id?: string | null
    items: Array<{
      question: string
      options: string[]
      kind?: 'text' | 'agent_spawn'
      agent_spawn?: {
        blueprint: string
        default_model: string
        default_thinking_level?: string | null
      }
    }>
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

export async function listTeamAgents(
  workspace?: string | null,
  mode?: 'coding' | null,
): Promise<TeamAgentsResponse> {
  const params = new URLSearchParams()
  if (workspace) params.set('workspace', workspace)
  // Which roster the workspace team uses — without it the backend assumes coding.
  if (workspace && mode) params.set('mode', mode)
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
  filters?: { mode?: 'work' | 'coding'; workspace?: string | null; project_id?: string | null },
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

// ── Session folders ───────────────────────────────────────────────────────────
// The list endpoint bundles each folder's newest sessions, so the sidebar's
// Folders tree comes from one request instead of a query per folder.

export async function listSessionFolders(
  mode: 'work' | 'coding' = 'work',
): Promise<SessionFolderListResponse> {
  const params = new URLSearchParams({ mode })
  const res = await fetch(`${apiBaseUrl()}/team/session-folders?${params}`)
  if (!res.ok) await parseDetailOrThrow(res, 'listSessionFolders')
  return res.json()
}

export async function listSessionFolderSessions(
  folderId: string,
  before?: string | null,
  limit = 40,
): Promise<SessionPageResponse> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (before) params.set('before', before)
  const res = await fetch(
    `${apiBaseUrl()}/team/session-folders/${encodeURIComponent(folderId)}/sessions?${params}`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'listSessionFolderSessions')
  return res.json()
}

export async function createSessionFolder(body: {
  name: string
  mode?: 'work' | 'coding'
  share_context?: boolean
}): Promise<SessionFolder> {
  const res = await fetch(`${apiBaseUrl()}/team/session-folders`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: 'work', ...body }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'createSessionFolder')
  return res.json()
}

export async function updateSessionFolder(
  id: string,
  body: Partial<{ name: string; share_context: boolean; sort_order: number }>,
): Promise<SessionFolder> {
  const res = await fetch(`${apiBaseUrl()}/team/session-folders/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'updateSessionFolder')
  return res.json()
}

export async function deleteSessionFolder(id: string): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/team/session-folders/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
  if (!res.ok) await parseDetailOrThrow(res, 'deleteSessionFolder')
}

/** File a session under a folder; pass `null` to move it back out. */
export async function setSessionFolder(
  sessionId: string,
  folderId: string | null,
): Promise<SessionResponse> {
  const res = await fetch(
    `${apiBaseUrl()}/team/sessions/${encodeURIComponent(sessionId)}/folder`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_id: folderId }),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'setSessionFolder')
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
  folder_id?: string | null
  model?: string | null
  thinkingLevel?: string | null
  create?: boolean
  tags?: string[]
  tagMatch?: 'exact' | 'contains'
  worktreeFrom?: string | null
  worktreeName?: string | null
  worktreeBranch?: string | null
}): Promise<TeamSessionResolveResponse> {
  const body: Record<string, string | string[] | boolean | null> = {
    mode: options.mode ?? 'work',
  }
  if (options.workspace !== undefined) body.workspace = options.workspace
  if (options.project_id !== undefined) body.project_id = options.project_id
  if (options.folder_id !== undefined) body.folder_id = options.folder_id
  if (options.model !== undefined) body.model = options.model
  if (options.thinkingLevel !== undefined) body.thinking_level = options.thinkingLevel
  if (options.create !== undefined) body.create = options.create
  if (options.tags !== undefined) body.tags = options.tags
  if (options.tagMatch !== undefined) body.tag_match = options.tagMatch
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
 * List every file under the session's agent workspace (``.evoflux/team/{sid}``).
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

/** Resolve a session workspace root without recursively listing its files. */
export async function getSessionWorkspaceRoot(sessionId: string): Promise<WorkspaceRootResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/${encodeURIComponent(sessionId)}/workspace`)
  if (!res.ok) await parseDetailOrThrow(res, 'getSessionWorkspaceRoot')
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

/** Build the URL for the backend-rendered document preview. */
export function workspaceDocumentPreviewUrl(sessionId: string, path: string): string {
  const encoded = path.split('/').map(encodeURIComponent).join('/')
  return withTokenParam(apiUrl(`/team/${encodeURIComponent(sessionId)}/document-preview/${encoded}`))
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

/** Build the URL for the backend-rendered document preview in Coding mode. */
export function codingWorkspaceDocumentPreviewUrl(workspace: string, path: string): string {
  const params = new URLSearchParams({ workspace, path })
  return withTokenParam(apiUrl(`/team/workspace/files/preview?${params}`))
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

/** Ask the coding workspace LSP to diagnose the current (possibly unsaved) buffer. */
export async function getCodingWorkspaceDiagnostics(
  workspace: string,
  path: string,
  content: string,
  signal?: AbortSignal,
): Promise<CodingDiagnosticsResponse> {
  const params = new URLSearchParams({ workspace })
  const res = await fetch(apiUrl(`/team/workspace/lsp/diagnostics?${params}`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ path, content }),
    signal,
  })
  if (!res.ok) await parseDetailOrThrow(res, 'getCodingWorkspaceDiagnostics')
  return res.json()
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

// ── WebBridge ───────────────────────────────────────────────────────────────

export async function getWebBridgeStatus(): Promise<WebBridgeStatusResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/webbridge/status`)
  if (!res.ok) await parseDetailOrThrow(res, 'getWebBridgeStatus')
  return res.json()
}

export async function listWebBridgeTeachDrafts(): Promise<WebBridgeTeachDraft[]> {
  const res = await fetch(`${apiBaseUrl()}/team/webbridge/teach-drafts/review`)
  if (!res.ok) await parseDetailOrThrow(res, 'listWebBridgeTeachDrafts')
  return res.json()
}

export async function approveWebBridgeTeachDraft(
  draftId: string,
): Promise<WebBridgeTeachDraft> {
  const res = await fetch(
    `${apiBaseUrl()}/team/webbridge/teach-drafts/${encodeURIComponent(draftId)}/approve`,
    { method: 'POST' },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'approveWebBridgeTeachDraft')
  return res.json()
}

export async function replayWebBridgeTeachDraft(
  draftId: string,
  parameters: Record<string, string>,
  executionId: string,
  startStep: number,
  idempotencyKey: string,
  restart = false,
): Promise<WebBridgeTeachDraftReplayResponse> {
  const res = await fetch(
    `${apiBaseUrl()}/team/webbridge/teach-drafts/${encodeURIComponent(draftId)}/replay`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': idempotencyKey,
      },
      body: JSON.stringify({
        parameters,
        execution_id: executionId,
        start_step: startStep,
        max_steps: 1,
        restart,
      }),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'replayWebBridgeTeachDraft')
  return res.json()
}

export async function resolveWebBridgeTeachReplay(
  draftId: string,
  executionId: string,
  outcome: 'completed' | 'not_completed',
): Promise<WebBridgeTeachDraft> {
  const res = await fetch(
    `${apiBaseUrl()}/team/webbridge/teach-drafts/${encodeURIComponent(draftId)}/replay/resolve`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        execution_id: executionId,
        outcome,
        user_confirmed: true,
      }),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'resolveWebBridgeTeachReplay')
  return res.json()
}

export async function deleteWebBridgeTeachDraft(draftId: string): Promise<void> {
  const res = await fetch(
    `${apiBaseUrl()}/team/webbridge/teach-drafts/${encodeURIComponent(draftId)}`,
    { method: 'DELETE' },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'deleteWebBridgeTeachDraft')
}

/**
 * Ask the backend to launch a local browser with the WebBridge extension
 * loaded. On 404 the thrown error's message carries the backend's
 * manual-install instructions (``detail``) — surface it as-is.
 */
export async function launchWebBridgeBrowser(): Promise<WebBridgeLaunchBrowserResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/webbridge/launch-browser`, { method: 'POST' })
  if (!res.ok) await parseDetailOrThrow(res, 'launchWebBridgeBrowser')
  return res.json()
}

/**
 * Audit trail of the commands the agent ran against the real browser — used
 * by the WebBridge status dialog so the user can review what the agent did.
 */
export async function getWebBridgeAudit(limit?: number): Promise<WebBridgeAuditResponse> {
  const qs = limit ? `?limit=${limit}` : ''
  const res = await fetch(`${apiBaseUrl()}/team/webbridge/audit${qs}`)
  if (!res.ok) await parseDetailOrThrow(res, 'getWebBridgeAudit')
  return res.json()
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
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/code-context/graph-data`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'listCrossRepoEdges')
  const data: ProjectCodeGraphData = await res.json()
  return status ? data.cross_repo_edges.filter((edge) => edge.status === status) : data.cross_repo_edges
}

// Single entry point for refreshing every repository-local target. The graph
// endpoint resolves cross-repository relationships from those targets on read.
export async function reindexProjectCodeGraph(
  projectId: string,
  options?: { full?: boolean; languages?: string[] },
): Promise<ProjectReindexStartedResponse> {
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/code-context/index`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        full: options?.full ?? false,
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
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/code-context/status`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'getProjectCodeGraphStatus')
  return res.json()
}

export async function searchProjectCodeGraph(
  projectId: string,
  query: string,
  options?: { kind?: string; limitPerRepo?: number },
): Promise<ProjectCodeSearchResponse> {
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/code-context/query`,
    {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: 'search',
        query,
        limit: Math.max(1, (options?.limitPerRepo ?? 10) * 8),
        refresh: true,
      }),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'searchProjectCodeGraph')
  const data: {
    hits: Array<{
      repository: string
      file_path: string
      language: string
      line_start: number
      line_end: number
      symbol: string | null
      repository_path: string | null
    }>
  } = await res.json()
  return {
    results: data.hits.map((hit) => {
      const qualified = hit.symbol ?? hit.file_path
      return {
        path: hit.repository_path ?? hit.repository,
        node: {
          id: `${hit.repository}:${hit.file_path}:${hit.line_start}`,
          workspace_id: hit.repository,
          kind: options?.kind ?? 'source',
          name: qualified.split('.').pop() ?? qualified,
          qualified_name: qualified,
          file_path: hit.file_path,
          language: hit.language,
          line_start: hit.line_start,
          line_end: hit.line_end,
          signature: null,
          docstring: null,
        },
      }
    }),
  }
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
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/code-context/graph-data${qs ? `?${qs}` : ''}`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'getProjectCodeGraphData')
  return res.json()
}

// ── Side Chat ─────────────────────────────────────────────────────────────────

/**
 * Create a side chat session linked to a main session.
 * The side chat gets read-only access to the main session's context.
 *
 * The backend returns a full SessionResponse (response_model=SessionResponse
 * on POST /team/{session_id}/side-chat) — the session's own id is `id`, not
 * `side_chat_id`; there is no `side_chat_id` field in that response at all.
 */
export async function createSideChat(mainSessionId: string): Promise<{ id: string; title: string | null }> {
  const res = await fetch(
    `${apiBaseUrl()}/team/${encodeURIComponent(mainSessionId)}/side-chat`,
    {
      method: 'POST',
      headers: { Accept: 'application/json' },
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'createSideChat')
  return res.json()
}

/**
 * Get messages for a side chat session.
 *
 * The backend serializes with the same ``MessageResponse`` shape as the main
 * chat history endpoint, so callers can reuse ``parseTeamBlocks`` to build
 * ContentBlock[] — keeping the side chat on the shared render pipeline.
 */
export async function getSideChatMessages(
  mainSessionId: string,
  sideChatId: string,
): Promise<MessageResponse[]> {
  const res = await fetch(
    `${apiBaseUrl()}/team/${encodeURIComponent(mainSessionId)}/side-chat/${encodeURIComponent(sideChatId)}/messages`,
    {
      method: 'GET',
      headers: { Accept: 'application/json' },
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'getSideChatMessages')
  return res.json()
}

/**
 * Send a message to a side chat session.
 * Returns immediately; the response is streamed via SSE.
 */
export async function sendSideChatMessage(
  mainSessionId: string,
  sideChatId: string,
  content: string,
): Promise<{ status: string; session_id: string }> {
  const res = await fetch(
    `${apiBaseUrl()}/team/${encodeURIComponent(mainSessionId)}/side-chat/${encodeURIComponent(sideChatId)}/message`,
    {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ content }),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'sendSideChatMessage')
  return res.json()
}

/**
 * Build the SSE stream URL for a side chat session.
 */
export function getSideChatStreamUrl(mainSessionId: string, sideChatId: string): string {
  return `${apiBaseUrl()}/team/${encodeURIComponent(mainSessionId)}/side-chat/${encodeURIComponent(sideChatId)}/stream`
}
