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
import type { InputBarHandle } from '../InputBar'

interface UseTeamSseArgs {
  sessionId: string | undefined
  agentWorkspace: string | null
  hasCodingWorkspace: boolean
  isCodingSessionLoading: boolean
  mode: 'forge' | 'coding' | 'aim'
  inputRef: RefObject<InputBarHandle | null>
}

export function useTeamSse({
  sessionId,
  agentWorkspace,
  hasCodingWorkspace,
  isCodingSessionLoading,
  mode,
  inputRef,
}: UseTeamSseArgs): RefObject<AbortController | null> {
  const connectStream  = useTeamStore((s) => s.connectStream)
  const loadTeamStatus = useTeamStore((s) => s.loadTeamStatus)
  const loadSession    = useTeamStore((s) => s.loadSession)
  const beginResolvedSession = useTeamStore((s) => s.beginResolvedSession)
  const consumeResolvedSessionReady = useTeamStore((s) => s.consumeResolvedSessionReady)

  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (hasCodingWorkspace)
      void loadTeamStatus(agentWorkspace, mode === 'aim' ? 'aim' : 'coding')
    if (isCodingSessionLoading) return
    if (!sessionId) return
    const store = useTeamStore.getState()
    if (store.sessionId === sessionId && store.isConnected) return
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

      // Clear the composer when switching sessions. The InputBar holds its
      // draft text and pending files in local state, so without an explicit
      // reset session A's typed-but-unsent message bleeds into session B.
      inputRef.current?.setValue('')
      inputRef.current?.setFiles([])
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
    ;(async () => {
      if (!consumeResolvedSessionReady(sessionId, agentWorkspace)) {
        await loadSession(
          sessionId,
          agentWorkspace,
          mode === 'aim' ? 'aim' : mode === 'coding' ? 'coding' : null,
        )
      }
      if (cancelled) return
      const controller = connectStream()
      if (controller) abortRef.current = controller
    })()

    return () => {
      cancelled = true
      abortRef.current?.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, agentWorkspace, hasCodingWorkspace, isCodingSessionLoading])

  useEffect(() => {
    if (!sessionId) return

    const resumeStream = () => {
      const state = useTeamStore.getState()
      if (state.sessionId !== sessionId) return
      if (state._workspace !== agentWorkspace) return
      if (state.isConnected && !state._unloading) return

      useTeamStore.setState({ _unloading: false })
      if (state.isTeamWorking) {
        void loadSession(
          sessionId,
          agentWorkspace,
          mode === 'aim' ? 'aim' : mode === 'coding' ? 'coding' : null,
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
