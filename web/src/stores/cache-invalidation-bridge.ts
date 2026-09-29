import type { InfiniteData, QueryClient } from '@tanstack/react-query'
import type { CacheInvalidation } from '@/stores/useTeamStore'
import type {
  CodingProject,
  CodingWorkspaceTreeResponse,
  SessionPageResponse,
  SessionResponse,
  WorkspaceGitDiffResponse,
} from '@/api/types'
import { getCodingWorkspaceGitDiff } from '@/api/client'
import { queryKeys } from '@/queries'
import { resolveRepositoryPath, sessionProject } from '@/utils/repository-paths'

type BridgeQueryClient = Pick<
  QueryClient,
  'invalidateQueries' | 'getQueryData' | 'setQueryData'
>

/** The repositories a session on *workspace* in *projectId* may touch. */
function sessionRepositories(
  queryClient: BridgeQueryClient,
  workspace: string,
  projectId: string | null | undefined,
): string[] {
  if (!projectId) return []
  const overview = queryClient.getQueryData<CodingWorkspaceTreeResponse>(queryKeys.codingOverview())
  const project =
    queryClient.getQueryData<CodingProject>(queryKeys.projects.detail(projectId))
    ?? overview?.projects.find((item) => item.id === projectId)
  if (!project) return []
  return sessionProject(project, workspace, overview).workspaces.map((item) => item.path)
}

let pendingEvents: CacheInvalidation[] = []
let pendingClient: BridgeQueryClient | null = null
let flushTimer: ReturnType<typeof setTimeout> | null = null

/** Coalesce adjacent SSE domain events into one cache refresh wave. */
export function scheduleCacheInvalidations(
  queryClient: BridgeQueryClient,
  events: readonly CacheInvalidation[],
): void {
  pendingClient = queryClient
  pendingEvents.push(...events)
  if (flushTimer !== null) return
  flushTimer = globalThis.setTimeout(() => {
    const client = pendingClient
    const batch = pendingEvents
    pendingClient = null
    pendingEvents = []
    flushTimer = null
    if (client && batch.length > 0) applyCacheInvalidations(client, batch)
  }, 50)
}

export function applyCacheInvalidations(
  queryClient: BridgeQueryClient,
  events: readonly CacheInvalidation[],
): void {
  const invalidated = new Set<string>()
  const pathUpdates = new Map<string, Set<string>>()
  const invalidate = (queryKey: readonly unknown[]) => {
    const signature = JSON.stringify(queryKey)
    if (invalidated.has(signature)) return
    invalidated.add(signature)
    queryClient.invalidateQueries({ queryKey })
  }
  for (const event of events) {
    switch (event.kind) {
      case 'wiki':
        invalidate(queryKeys.wiki.all())
        break
      case 'workspace_files':
        invalidate(queryKeys.team.files(event.sessionId))
        break
      case 'coding_workspace':
        // No paths (a shell command, say): any of the session's
        // repositories may have changed.
        for (const workspace of [
          event.workspace,
          ...sessionRepositories(queryClient, event.workspace, event.projectId),
        ]) {
          invalidate(queryKeys.coding.files(workspace))
          invalidate(queryKeys.coding.diff(workspace))
          invalidate(queryKeys.coding.status(workspace))
        }
        break
      case 'coding_workspace_paths': {
        // A tool may have written into another repository of the project
        // (`../web/src/app.ts`, or an absolute path): refresh the repository
        // that owns each path, with the path relative to it.
        const repositories = sessionRepositories(queryClient, event.workspace, event.projectId)
        for (const raw of event.paths) {
          const owned = resolveRepositoryPath(event.workspace, repositories, raw)
          if (!owned) continue
          invalidate(queryKeys.coding.files(owned.workspace))
          invalidate(queryKeys.coding.status(owned.workspace))
          if (!pathUpdates.has(owned.workspace)) pathUpdates.set(owned.workspace, new Set())
          pathUpdates.get(owned.workspace)?.add(owned.path)
        }
        break
      }
      case 'scheduler':
        invalidate(queryKeys.scheduler.list())
        break
      case 'todos':
        invalidate(queryKeys.todos(event.sessionId))
        break
      case 'team_agents':
        invalidate(queryKeys.teamAgents())
        break
      case 'team_sessions':
        invalidate(queryKeys.team.sessions.all())
        break
    }
  }
  for (const [workspace, paths] of pathUpdates) {
    void patchCodingDiffForPaths(queryClient, workspace, [...paths])
  }
}

async function patchCodingDiffForPaths(
  queryClient: BridgeQueryClient,
  workspace: string,
  paths: string[],
): Promise<void> {
  if (paths.length === 0) return
  const key = queryKeys.coding.diff(workspace)
  const cached = queryClient.getQueryData<WorkspaceGitDiffResponse>(key)

  if (!cached || !cached.is_git_repo) return

  let scoped: WorkspaceGitDiffResponse
  try {
    scoped = await getCodingWorkspaceGitDiff(workspace, paths)
  } catch {
    queryClient.invalidateQueries({ queryKey: key })
    return
  }

  const merged = mergeScopedDiff(cached.diff, scoped.diff, paths)
  queryClient.setQueryData<WorkspaceGitDiffResponse>(key, {
    ...cached,
    diff: merged,
    truncated: cached.truncated || scoped.truncated,
    untracked: nextUntracked(cached.untracked, scoped.untracked, paths),
  })
}

const DIFF_HEADER_RE = /\ndiff --git a\/(.+?) b\/.+?(?=\ndiff --git |$)/gs
const FIRST_DIFF_HEADER_RE = /^diff --git a\/(.+?) b\/.+?(?=\ndiff --git |$)/s

export function mergeScopedDiff(
  existingDiff: string,
  scopedDiff: string,
  paths: string[],
): string {
  if (!existingDiff) return scopedDiff
  const pathSet = new Set(paths)

  const kept: string[] = []

  let cursor = 0
  const firstMatch = FIRST_DIFF_HEADER_RE.exec(existingDiff)
  if (firstMatch) {
    const path = firstMatch[1]
    if (!pathSet.has(path)) kept.push(firstMatch[0])
    cursor = firstMatch[0].length
  }

  const rest = existingDiff.slice(cursor)
  for (const match of rest.matchAll(DIFF_HEADER_RE)) {
    const path = match[1]
    if (!pathSet.has(path)) kept.push(match[0])
  }

  const keptText = kept.join('')
  const scoped = scopedDiff.startsWith('\n') ? scopedDiff : scopedDiff
  if (!keptText) return scoped
  if (!scoped) return keptText
  return scoped.startsWith('\n') || keptText.endsWith('\n')
    ? keptText + scoped
    : keptText + '\n' + scoped
}

function nextUntracked(
  cached: string[] | undefined,
  scoped: string[] | undefined,
  paths: string[],
): string[] | undefined {
  if (!cached && !scoped) return undefined
  const pathSet = new Set(paths)
  const carry = (cached ?? []).filter((p) => !pathSet.has(p))
  return [...carry, ...(scoped ?? [])]
}

function isInfiniteSessionData(value: unknown): value is InfiniteData<SessionPageResponse> {
  return Boolean(
    value &&
    typeof value === 'object' &&
    'pages' in value &&
    Array.isArray(value.pages),
  )
}

export function patchSessionTitle(
  queryClient: Pick<QueryClient, 'setQueriesData'>,
  sessionId: string,
  title: string,
): void {
  queryClient.setQueriesData<InfiniteData<SessionPageResponse>>(
    { queryKey: queryKeys.team.sessions.all() },
    (old) => {
      if (!isInfiniteSessionData(old)) return old
      return {
        ...old,
        pages: old.pages.map((page) => ({
          ...page,
          data: page.data.map((s) => s.id === sessionId ? { ...s, title } : s),
        })),
      }
    },
  )
}

function prependSessionToInfiniteData(
  old: InfiniteData<SessionPageResponse> | undefined,
  session: SessionResponse,
): InfiniteData<SessionPageResponse> | undefined {
  if (!isInfiniteSessionData(old)) return old
  if (old.pages.some((page) => page.data.some((item) => item.id === session.id))) return old
  const [first, ...rest] = old.pages
  if (!first) return old
  return {
    ...old,
    pages: [
      {
        ...first,
        data: [session, ...first.data],
      },
      ...rest,
    ],
  }
}

export function prependSession(
  queryClient: Pick<QueryClient, 'setQueryData'>,
  session: SessionResponse,
): void {
  // Normalize: undefined/null/'normal' → 'work'; 'coding' stays as-is.
  // Must write to the mode-keyed cache entry that each sidebar reads.
  const raw = session.mode ?? 'work'
  const mode: 'work' | 'coding' = raw === 'coding' ? 'coding' : 'work'
  queryClient.setQueryData<InfiniteData<SessionPageResponse>>(
    queryKeys.team.sessions.infinite(mode),
    (old) => prependSessionToInfiniteData(old, session),
  )
}
