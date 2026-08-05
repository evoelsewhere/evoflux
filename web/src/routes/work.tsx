import { useRef, useEffect, useLayoutEffect, useState } from 'react'
import { Outlet, useParams, useNavigate } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { TeamChatView } from '@/components/TeamChatView'
import { getTeamSession, resolveTeamSession } from '@/api/client'
import { useTeamStore } from '@/stores/useTeamStore'
import { useToastStore } from '@/stores/useToastStore'
import { useUIStore } from '@/stores/useUIStore'
import { applyCacheInvalidations, patchSessionTitle } from '@/stores/cache-invalidation-bridge'
import { queryKeys } from '@/queries'
import { clearLastCodingFocus, codingFocusId, isProjectFocusId, isWorkspaceUnavailableError, saveLastCodingFocus, saveLastCodingWorkspace, workspaceFromSession } from '@/utils/workspace'

/**
 * Layout route for /, /coding, and their session routes.
 * Stays mounted across URL changes — handles navigation when a new
 * team session_id arrives from POST /team/chat.
 */
function TeamLayoutBase({ forcedMode }: { forcedMode?: 'work' | 'coding' }) {
  const params = useParams({ strict: false }) as Record<string, string>
  const sessionId = params.sessionId as string | undefined
  const focusId = params.focusId as string | undefined
  const mode = forcedMode ?? 'work'
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const workspaceRef = useRef<string | null>(null)
  const cachedSessionPages = queryClient.getQueryData<{
    pages: Array<{ data: Array<{ id: string; workspace?: string | null; project_id?: string | null }> }>
  }>(queryKeys.team.sessions.infinite(mode === 'coding' ? 'coding' : 'work'))
  const cachedSession = sessionId
    ? cachedSessionPages?.pages
      .flatMap((page) => page.data)
      .find((session) => session.id === sessionId)
    : undefined
  const sessionQuery = useQuery({
    queryKey: queryKeys.team.sessions.detail(sessionId ?? ''),
    queryFn: () => getTeamSession(sessionId as string),
    enabled: mode === 'coding' && Boolean(sessionId) && !cachedSession?.workspace,
    staleTime: 30_000,
  })
  const workspace = workspaceFromSession(mode, sessionId, cachedSession?.workspace ?? sessionQuery.data?.workspace)
  const projectId = mode === 'coding' && sessionId
    ? (cachedSession?.project_id ?? sessionQuery.data?.project_id ?? null)
    : null

  useEffect(() => {
    // project_id (when set) always wins inside saveLastCodingFocus — safe to
    // call unconditionally once workspace is known, project or not. Doing
    // this generically here (rather than at each call site that starts a
    // session) is exactly why this needs to be project-aware: a project
    // session's `workspace` is only its representative repo, and persisting
    // that alone would silently drop the project context on restore.
    if (mode === 'coding' && workspace) saveLastCodingFocus({ project_id: projectId, workspace })
  }, [mode, workspace, projectId])

  // /coding/$focusId (no sessionId yet) — the URL already names a workspace
  // or project directly; resolve/create its session and append it to the URL.
  // A bare old-style /coding/{sessionId} link (from before this route
  // existed) also lands here, since it's structurally the same single
  // segment — project ids and session ids are both plain UUIDs, so there's
  // no way to tell them apart without asking the backend. If focusId
  // doesn't resolve as a project/workspace, fall back to treating it as a
  // legacy session id and upgrade the URL to the real focus once known.
  useEffect(() => {
    if (mode !== 'coding' || sessionId || !focusId) return
    let cancelled = false
    ;(async () => {
      const current = useTeamStore.getState()
      try {
        const session = await resolveTeamSession({
          mode: 'coding',
          ...(isProjectFocusId(focusId)
            ? { project_id: focusId }
            : { workspace: focusId }),
          model: current.sessionModel,
          thinkingLevel: current.sessionThinkingLevel,
        })
        if (cancelled || sessionIdRef.current) return
        current.beginResolvedSession(session.id, {
          mode: 'coding',
          workspace: session.workspace ?? (isProjectFocusId(focusId) ? null : focusId),
          model: session.model ?? current.sessionModel,
          thinkingLevel: session.thinking_level ?? current.sessionThinkingLevel,
        })
        void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessions.all() })
        navigate({
          to: '/coding/$focusId/$sessionId',
          params: { focusId, sessionId: session.id },
          replace: true,
        })
      } catch (err) {
        if (cancelled) return
        try {
          const legacySession = await getTeamSession(focusId)
          if (cancelled || sessionIdRef.current) return
          const realFocusId = codingFocusId({
            project_id: legacySession.project_id,
            workspace: legacySession.workspace,
          })
          if (!realFocusId) throw err
          navigate({
            to: '/coding/$focusId/$sessionId',
            params: { focusId: realFocusId, sessionId: legacySession.id },
            replace: true,
          })
        } catch {
          if (cancelled) return
          clearLastCodingFocus(focusId)
          if (isWorkspaceUnavailableError(err)) {
            useTeamStore.setState((state) => {
              state.error = null
            })
            useToastStore.getState().push({
              tone: 'info',
              title: 'Workspace moved or unavailable',
              description: 'The saved folder no longer exists. Open the repository from its new location to continue.',
            }, 7000)
            navigate({ to: '/coding', replace: true })
            return
          }
          useTeamStore.setState((state) => {
            state.error = err instanceof Error ? err.message : 'Failed to open workspace'
          })
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [mode, navigate, queryClient, sessionId, focusId])

  const storeError = useTeamStore((s) => s.error)
  const [retryKey, setRetryKey] = useState(0)

  const navigateRef = useRef(navigate)
  const sessionIdRef = useRef(sessionId)
  const modeRef = useRef(mode)
  useEffect(() => {
    navigateRef.current = navigate
    sessionIdRef.current = sessionId
    modeRef.current = mode
    workspaceRef.current = workspace
  })

  // Keep ``useTeamStore._workspace`` and ``projectId`` in sync with the
  // URL-derived session the moment we render the layout — before the async
  // ``loadSession`` round-trip in TeamChatView.  CodingWorkspacePanel reads
  // ``projectId`` to decide whether to show multi-repo (DiffReviewPanel) or
  // single-workspace mode; priming it here prevents the single-workspace
  // flash on initial load / navigation.
  const cachedProjectId = cachedSession?.project_id ?? sessionQuery.data?.project_id ?? null
  useLayoutEffect(() => {
    if (mode === 'coding' && !sessionId && !focusId) {
      const state = useTeamStore.getState()
      if (state.sessionId || state._workspace || state.projectId) {
        state.newSession()
      }
      return
    }
    useTeamStore.setState((state) => {
      if (mode === 'coding') {
        state._workspace = workspace ?? null
        state.projectId = cachedProjectId ?? null
      } else {
        // Proactively clear a stale project binding when a non-coding route
        // renders, rather than waiting for the async loadSession round-trip.
        state.projectId = null
      }
    })
  }, [mode, workspace, cachedProjectId, sessionId, focusId])

  useEffect(() => {
    if (sessionId) return
    if (mode === 'coding' && !workspace) return
    let cancelled = false
    ;(async () => {
      const current = useTeamStore.getState()
      // Use undefined (not null) when no model is known, so resolveTeamSession
      // omits the field and the backend applies its default instead of
      // rejecting with "Choose a model from the registry". This also avoids
      // carrying a null model from a different mode's stale session into the
      // new session.
      const model = (current.sessionId && current.sessionModel) ? current.sessionModel : undefined
      const thinkingLevel = (current.sessionId && current.sessionThinkingLevel) ? current.sessionThinkingLevel : undefined
      try {
        const session = await resolveTeamSession({
          mode,
          workspace: mode === 'coding' ? workspace : null,
          model,
          thinkingLevel,
        })
        if (cancelled || sessionIdRef.current) return
        useTeamStore.getState().beginResolvedSession(session.id, {
          mode,
          workspace: session.workspace ?? workspace,
          model: session.model ?? model,
          thinkingLevel: session.thinking_level ?? thinkingLevel,
        })
        void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessions.all() })
        if (mode === 'coding' && workspace) {
          saveLastCodingWorkspace(workspace)
        }
        navigate({
          to: '/$sessionId',
          params: { sessionId: session.id },
          replace: true,
        })
      } catch (err) {
        if (cancelled) return
        useTeamStore.setState((state) => {
          state.error = err instanceof Error ? err.message : 'Failed to resolve session'
        })
      }
    })()
    return () => {
      cancelled = true
    }
    // retryKey is intentionally included so the retry button can re-trigger this effect.
  }, [mode, navigate, queryClient, sessionId, workspace, retryKey])

  // When team store gets a new sessionId, navigate to the matching session route.
  useEffect(() => {
    return useTeamStore.subscribe((state, prev) => {
      if (state.sessionId && state.sessionId !== prev.sessionId && !sessionIdRef.current) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessions.all() })
        void queryClient.refetchQueries({ queryKey: queryKeys.team.sessions.infinite(), type: 'active' })
        if (modeRef.current === 'coding') {
          const workspace = workspaceRef.current
          if (workspace) saveLastCodingFocus({ project_id: state.projectId, workspace })
          const newFocusId = codingFocusId({ project_id: state.projectId, workspace })
          navigateRef.current(
            newFocusId
              ? { to: '/coding/$focusId/$sessionId', params: { focusId: newFocusId, sessionId: state.sessionId }, replace: true }
              : { to: '/coding', replace: true },
          )
        } else {
          navigateRef.current({
            to: '/$sessionId',
            params: { sessionId: state.sessionId },
            replace: true,
          })
        }
      }

      // When title_update arrives, patch the cached team session list
      // in-place — no re-fetch. See ``patchSessionTitle``.
      if (state.sessionTitle && state.sessionTitle !== prev.sessionTitle && state.sessionId) {
        patchSessionTitle(queryClient, state.sessionId, state.sessionTitle)
        void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessions.infinite() })
      }

      // Cache-invalidation bridge: the SSE reducer enqueues domain
      // events on ``cacheInvalidations`` (memory, workspace_files,
      // scheduler, todos) rather than calling
      // ``queryClient.invalidateQueries`` directly, so the store
      // stays free of TanStack imports.  Drain the queue and hand
      // the events to the bridge helper, which owns the mapping.
      if (state.cacheInvalidations !== prev.cacheInvalidations && state.cacheInvalidations.length > 0) {
        applyCacheInvalidations(queryClient, useTeamStore.getState()._drainCacheInvalidations())
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <>
      <TeamChatView
        sessionId={sessionId}
        mode={mode}
        workspace={workspace}
        codingSessionLoading={
          mode === 'coding' &&
          ((Boolean(sessionId) && !workspace && sessionQuery.isLoading) ||
            (Boolean(focusId) && !sessionId))
        }
      />
      <Outlet />
      {storeError && !sessionId && (
        <div
          className="fixed inset-0 z-(--z-overlay) flex items-center justify-center bg-(--color-overlay) p-4"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="work-backend-error-title"
        >
          <div className="flex w-full max-w-sm flex-col gap-4 rounded-xl border border-(--color-border) bg-(--bg-card) p-5 shadow-2xl">
            <div>
              <p id="work-backend-error-title" className="text-sm font-semibold text-(--color-text)">Backend connection failed</p>
              <p className="mt-1 text-xs leading-5 text-(--color-text-muted)">{storeError}</p>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => {
                  useTeamStore.setState((state) => { state.error = null })
                  setRetryKey((k) => k + 1)
                }}
                className="flex-1 rounded-md border border-(--color-border) bg-(--bg-key) px-3 py-2 text-xs font-medium text-(--color-text) hover:bg-(--bg-page)"
              >
                Retry
              </button>
              <button
                type="button"
                onClick={() => useUIStore.getState().openSettings('connection')}
                className="flex-1 rounded-md border border-(--color-border-strong) bg-(--bg-key) px-3 py-2 text-xs font-medium text-(--color-text) hover:bg-(--bg-page)"
              >
                Configure Backend
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

export function TeamLayout() {
  return <TeamLayoutBase />
}

export function CodingLayout() {
  return <TeamLayoutBase forcedMode="coding" />
}
