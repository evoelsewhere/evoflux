/**
 * useTeamSse — mount-time SSE connect + session restore for TeamChatView
 * (extracted unchanged).
 *
 * Carefully sequenced so ``loadSession`` runs *before* ``connectStream``
 * to avoid wiping replayed mid-turn state — see the comment inside the
 * init effect. Also owns the pageshow/visibilitychange resume wiring.
 *
 * Returns the shared ``abortRef`` so the parent (new-session flow) can
 * abort the in-flight stream.
 */
import { useEffect, useRef, type RefObject } from 'react'
import { useTeamStore } from '@/stores/useTeamStore'

interface UseTeamSseArgs {
  sessionId: string | undefined
  agentWorkspace: string | null
  hasCodingWorkspace: boolean
  isCodingSessionLoading: boolean
  mode: 'work' | 'coding'
  reloadToken?: number
}

function isLiveStream(
  store: ReturnType<typeof useTeamStore.getState>,
  sessionId: string,
  workspace: string | null,
): AbortController | null {
  const controller = store._abortController
  if (!controller || controller.signal.aborted) return null
  if (store.sessionId !== sessionId) return null
  if (store._workspace !== workspace) return null
  if (!store.isConnected) return null
  return controller
}

function markStreamStopped(controller: AbortController) {
  const state = useTeamStore.getState()
  if (state._abortController !== controller) return
  controller.abort()
  // readSSE swallows AbortError without onDone/onError, so clear the
  // connected flag here — otherwise the next effect early-path treats a
  // dead socket as live and never resubscribes.
  useTeamStore.setState({ isConnected: false, _abortController: null })
}

export function useTeamSse({
  sessionId,
  agentWorkspace,
  hasCodingWorkspace,
  isCodingSessionLoading,
  mode,
  reloadToken = 0,
}: UseTeamSseArgs): RefObject<AbortController | null> {
  const connectStream  = useTeamStore((s) => s.connectStream)
  const loadTeamStatus = useTeamStore((s) => s.loadTeamStatus)
  const loadSession    = useTeamStore((s) => s.loadSession)
  const beginResolvedSession = useTeamStore((s) => s.beginResolvedSession)
  const consumeResolvedSessionReady = useTeamStore((s) => s.consumeResolvedSessionReady)

  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (hasCodingWorkspace)
      void loadTeamStatus(agentWorkspace, 'coding', sessionId)
    // A draft has no history to load, but it still needs a lead: the model
    // picker, the composer's capabilities and the optimistic user bubble all
    // hang off the roster, which otherwise only arrives with a session.
    else if (!sessionId)
      void loadTeamStatus(null, mode === 'coding' ? 'coding' : null, null)
    if (isCodingSessionLoading) return
    if (!sessionId) return
    const store = useTeamStore.getState()
    const isSameSession =
      store.sessionId === sessionId && store._workspace === agentWorkspace

    // Reset (not just re-point) on every genuine switch — a bare
    // `setState({ sessionId })` left `isConnected`/`agentStreams` holding
    // the PREVIOUS session's data, so the skeleton below (gated on
    // `sessionId && !isConnected`) never got a chance to render: the old
    // session's stale messages kept showing with no loading feedback while
    // `loadSession` fetched the new one in the background.
    if (!isSameSession) {
      beginResolvedSession(sessionId, { mode, workspace: agentWorkspace })
      // Composer drafts are owned by InputBar (per-session Map). Do not
      // clear here — racing setValue('') after InputBar restores would
      // wipe the restored draft (or save '' over the previous session).
    }

    // Order matters: load prior-turn history FIRST, then open the SSE.
    //
    // Before this ordering, `connectStream()` started SSE replay (which
    // writes synthetic thinking/message events into `currentBlocks`)
    // while `loadSession()` was still inflight. When `loadSession`
    // resolved it unconditionally set `currentBlocks = []`, wiping the
    // replayed state. On mid-turn refresh the UI looked blank until the
    // next live chunk arrived — often until `done`.
    //
    // Awaiting the DB read first means `loadSession` has already committed
    // `blocks` and emptied `currentBlocks` by the time any SSE event is
    // dispatched, so replay + live events accumulate cleanly.
    let cancelled = false
    const live = isSameSession ? isLiveStream(store, sessionId, agentWorkspace) : null

    if (live) {
      // Adopt the stream opened by sendMessage/continue (or a prior effect)
      // but still register cleanup — a bare `return` left unmount with a
      // live fetch and treated aborted sockets as connected forever.
      abortRef.current = live
    } else {
      ;(async () => {
        if (!consumeResolvedSessionReady(sessionId, agentWorkspace)) {
          await loadSession(
            sessionId,
            agentWorkspace,
            mode === 'coding' ? 'coding' : null,
          )
        }
        if (cancelled) return
        const controller = connectStream()
        if (controller) abortRef.current = controller
      })()
    }

    return () => {
      cancelled = true
      const fromRef = abortRef.current
      abortRef.current = null
      // sendMessage / continue replace `_abortController` without updating
      // this ref — prefer the store's live controller for this session so
      // unmount actually tears down the socket instead of no-op'ing on a
      // stale aborted handle.
      const storeNow = useTeamStore.getState()
      const liveNow = storeNow._abortController
      const controller =
        liveNow &&
        !liveNow.signal.aborted &&
        storeNow.sessionId === sessionId &&
        storeNow._workspace === agentWorkspace
          ? liveNow
          : fromRef
      if (!controller) return
      markStreamStopped(controller)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, agentWorkspace, hasCodingWorkspace, isCodingSessionLoading, mode, reloadToken])

  useEffect(() => {
    if (!sessionId) return

    const resumeStream = () => {
      const state = useTeamStore.getState()
      if (state.sessionId !== sessionId) return
      if (state._workspace !== agentWorkspace) return
      if (isLiveStream(state, sessionId, agentWorkspace) && !state._unloading) return

      useTeamStore.setState({ _unloading: false })
      if (state.isTeamWorking) {
        void loadSession(
          sessionId,
          agentWorkspace,
          mode === 'coding' ? 'coding' : null,
        ).then(() => {
          const current = useTeamStore.getState()
          if (current.sessionId !== sessionId || current._workspace !== agentWorkspace) return
          abortRef.current = connectStream()
        })
      } else {
        abortRef.current = connectStream()
      }
    }

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') resumeStream()
    }

    window.addEventListener('pageshow', resumeStream)
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      window.removeEventListener('pageshow', resumeStream)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, agentWorkspace, mode])

  return abortRef
}
