import { useRef, useEffect, useLayoutEffect, useState } from 'react'
import { Outlet, useParams, useNavigate } from '@tanstack/react-router'
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { TeamChatView } from '@/components/TeamChatView'
import { findTeamSession, getProject, getTeamSessionMetadata } from '@/api/client'
import type { CodingWorkspaceTreeResponse } from '@/api/types'
import { useTeamStore } from '@/stores/useTeamStore'
import { useToastStore } from '@/stores/useToastStore'
import { useUIStore } from '@/stores/useUIStore'
import { patchSessionTitle, scheduleCacheInvalidations } from '@/stores/cache-invalidation-bridge'
import { queryKeys } from '@/queries'
import { clearLastCodingFocus, codingFocusId, isProjectFocusId, isWorkspaceUnavailableError, saveLastCodingFocus, workspaceFromSession } from '@/utils/workspace'

/**
 * A project's primary repo — the same first entry the backend derives when a
 * session names only the project. Served from the sidebar's cached tree when
 * it is there, fetched once when the URL was opened cold.
 */
async function projectPrimaryWorkspace(
  queryClient: QueryClient,
  projectId: string,
): Promise<string | null> {
  const cached = queryClient
    .getQueryData<CodingWorkspaceTreeResponse>(queryKeys.codingOverview())
    ?.projects.find((project) => project.id === projectId)
  if (cached) return cached.workspaces[0]?.path ?? null
  try {
    const project = await queryClient.fetchQuery({
      queryKey: queryKeys.projects.detail(projectId),
      queryFn: () => getProject(projectId),
      staleTime: 60_000,
    })
    return project.workspaces[0]?.path ?? null
  } catch {
    // The panels can live without it; the send still names the project.
    return null
  }
}

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
    queryKey: queryKeys.team.sessions.metadata(sessionId ?? ''),
    queryFn: ({ signal }) => getTeamSessionMetadata(sessionId as string, signal),
    enabled: mode === 'coding' && Boolean(sessionId) && !cachedSession?.workspace,
    staleTime: 30_000,
  })
  // A Coding draft has no session row to read a workspace from, but it does
  // know the repo (and project) it was opened on. Without this fallback the
  // chat view sees a null workspace and renders the "open a repository" empty
  // state — which has no composer, so the message that would create the
  // session can never be typed.
  //
  // It has to outlive the draft itself. The first message sets the store's
  // session id immediately, while the row's own workspace only arrives with
  // the metadata fetch that id triggers — roughly half a second later. Trust
  // the store across that gap and the repo simply stays; drop it the moment
  // the draft ends and the coding view blanks and refills, re-fetching the
  // roster, skills and workspace tree once without a repo and once with it.
  //
  // The condition is "the store is on the session the URL names", so a switch
  // to another session — where the URL moves first and the store still holds
  // the previous one — falls through to the loading state instead of flashing
  // the old repo.
  const isDraftSession = useTeamStore((s) => s.sessionId === null && s.newChatDraft !== null)
  const storeOwnsUrlSession = useTeamStore(
    (s) => (sessionId ? s.sessionId === sessionId : s.newChatDraft !== null || s.sessionId !== null),
  )
  const draftWorkspace = useTeamStore((s) => s._workspace)
  const draftProjectId = useTeamStore((s) => s.projectId)
  // Kept separate from `workspace` below: the layout effect that clears a
  // stale focus on bare `/coding` depends on this value, and feeding it the
  // draft's workspace would make a just-opened draft re-run that effect one
  // render before the route catches up — wiping the draft it was opening.
  const sessionWorkspace = workspaceFromSession(mode, sessionId, cachedSession?.workspace ?? sessionQuery.data?.workspace)
  const workspace = sessionWorkspace
    ?? (mode === 'coding' && storeOwnsUrlSession ? draftWorkspace : null)
  const projectId = mode === 'coding'
    ? ((sessionId ? (cachedSession?.project_id ?? sessionQuery.data?.project_id) : null)
      ?? (storeOwnsUrlSession ? draftProjectId : null))
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
    // A "+" already put us in a fresh draft on this very focus — leave it
    // alone rather than pulling the user back into an older session.
    const drafting = useTeamStore.getState()
    if (
      !drafting.sessionId &&
      drafting.newChatDraft &&
      (isProjectFocusId(focusId)
        ? drafting.projectId === focusId
        : drafting._workspace === focusId)
    ) return
    let cancelled = false
    const controller = new AbortController()
    ;(async () => {
      const current = useTeamStore.getState()
      try {
        const session = await findTeamSession({
          mode: 'coding',
          ...(isProjectFocusId(focusId)
            ? { project_id: focusId }
            : { workspace: focusId }),
        })
        if (cancelled || sessionIdRef.current) return
        if (!session) {
          // Nothing has been said in this repo/project yet. Open a draft on
          // it and let the first message create the session — no empty row
          // for a chat the user may never write in.
          const isProject = isProjectFocusId(focusId)
          // A project draft still needs its primary repo: the panels read it,
          // and letting it arrive later would look like a workspace switch
          // mid-turn and reset the chat the first message just started.
          const draftWorkspace = isProject
            ? (await projectPrimaryWorkspace(queryClient, focusId))
            : focusId
          if (cancelled || sessionIdRef.current) return
          current.beginResolvedSession(null, {
            mode: 'coding',
            workspace: draftWorkspace,
            projectId: isProject ? focusId : null,
            model: current.sessionId ? current.sessionModel : null,
            thinkingLevel: current.sessionId ? current.sessionThinkingLevel : null,
          })
          return
        }
        current.beginResolvedSession(session.id, {
          mode: 'coding',
          workspace: session.workspace ?? (isProjectFocusId(focusId) ? null : focusId),
          projectId: session.project_id ?? null,
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
          const legacySession = await getTeamSessionMetadata(focusId, controller.signal)
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
      controller.abort()
    }
  }, [mode, navigate, queryClient, sessionId, focusId])

  const storeError = useTeamStore((s) => s.error)
  const [retryKey, setRetryKey] = useState(0)

  const navigateRef = useRef(navigate)
  const sessionIdRef = useRef(sessionId)
  const modeRef = useRef(mode)
  // Route-driven child effects may attach the selected session immediately
  // after navigation. Sync these refs during the layout phase so the store
  // subscriber below sees the new URL and does not redirect that session
  // back to the bare /coding route.
  useLayoutEffect(() => {
    navigateRef.current = navigate
    sessionIdRef.current = sessionId
    modeRef.current = mode
    workspaceRef.current = workspace
  }, [navigate, sessionId, mode, workspace])

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
        // A draft on a focus owns its own workspace/project — they were set
        // when it opened and there is no session to derive them from, so
        // priming from the (null) session values here would erase them.
        if (!sessionId) return
        // Same for the session a draft has just become: its row is not in
        // any cache yet, so both values below read null for as long as the
        // metadata fetch takes. Writing them would erase the repo the chat
        // was started in and blank the coding view mid-turn. Priming is for
        // a session we know something about; when we know nothing and the
        // store is already on this session, leave it alone.
        if (
          useTeamStore.getState().sessionId === sessionId
          && sessionWorkspace === null
          && cachedProjectId === null
        ) return
        state._workspace = sessionWorkspace ?? null
        state.projectId = cachedProjectId ?? null
      } else {
        // Proactively clear a stale project binding when a non-coding route
        // renders, rather than waiting for the async loadSession round-trip.
        state.projectId = null
      }
    })
  }, [mode, sessionWorkspace, cachedProjectId, sessionId, focusId])

  // Bare ``/`` — reopen the newest Work chat, or settle into a draft.
  //
  // Nothing is created here any more. A chat the user deliberately started
  // (New chat, or a folder's +) has already marked itself a draft and is left
  // exactly as it is; a cold landing looks for a session to reopen and, when
  // there is none, opens a draft of its own. Either way the first message is
  // what brings a session into being.
  useEffect(() => {
    if (sessionId || mode === 'coding') return
    if (useTeamStore.getState().newChatDraft) return
    let cancelled = false
    ;(async () => {
      try {
        const session = await findTeamSession({ mode: 'work', workspace: null })
        if (cancelled || sessionIdRef.current) return
        const current = useTeamStore.getState()
        if (current.newChatDraft) return
        if (!session) {
          current.beginResolvedSession(null, { mode: 'work' })
          return
        }
        current.beginResolvedSession(session.id, {
          mode: 'work',
          model: session.model,
          thinkingLevel: session.thinking_level,
        })
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
  }, [mode, navigate, sessionId, retryKey])

  // When team store gets a new sessionId, navigate to the matching session route.
  useEffect(() => {
    return useTeamStore.subscribe((state, prev) => {
      if (state.sessionId && state.sessionId !== prev.sessionId && !sessionIdRef.current) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessions.all() })
        // A draft's first message may have just filed a brand-new session
        // into a folder — the folder lists carry their own sessions and
        // counts, so they need the same nudge.
        void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessionFoldersAll() })
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
      }

      // Cache-invalidation bridge: the SSE reducer enqueues domain
      // events on ``cacheInvalidations`` (memory, workspace_files,
      // scheduler, todos) rather than calling
      // ``queryClient.invalidateQueries`` directly, so the store
      // stays free of TanStack imports.  Drain the queue and hand
      // the events to the bridge helper, which owns the mapping.
      if (state.cacheInvalidations !== prev.cacheInvalidations && state.cacheInvalidations.length > 0) {
        scheduleCacheInvalidations(queryClient, useTeamStore.getState()._drainCacheInvalidations())
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
            (Boolean(focusId) && !sessionId && !isDraftSession))
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
