/**
 * useSideChat — state management and API integration for the Side Chat panel.
 *
 * Mirrors the main chat architecture so both surfaces share one pipeline:
 *   - History is fetched as MessageResponse[] and parsed with the shared
 *     `parseTeamBlocks` into finalized ContentBlock[] (`blocks`).
 *   - SSE events are reduced into the live `currentBlocks` tail with the
 *     shared helpers from `utils/blocks.ts` (appendText/initTool/completeTool/
 *     ...) — the exact same reducers the main chat's sse-reducer uses.
 *   - Rendering is left to `SideChatTranscript`, which uses the shared
 *     `BlockRenderer` — identical look & behavior to the main chat.
 *
 * Stream lifecycle mirrors the main chat's `connectStream`: the stream is
 * (re)attached AFTER the send POST returns, not persistently. The backend's
 * `stream_store.attach()` only yields while a turn is active (it replays the
 * buffered current turn, then live events) — attaching before a turn exists
 * returns an empty stream and closes immediately, and a fresh `init_turn`
 * drains pre-existing subscribers. The replay buffer covers the POST→attach
 * gap, so no events are lost. Attaching on session open also re-syncs an
 * in-flight run (mid-turn replay) after a page reload.
 *
 * The hook is meant to be lifted above the panel (TeamChatView) so closing
 * the panel does not destroy the session or an in-flight generation.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createSideChat,
  getSideChatMessages,
  sendSideChatMessage,
  getSideChatStreamUrl,
  postTeamChat,
} from '@/api/client'
import { readSSE } from '@/api/sse'
import { parseTeamBlocks } from '@/utils/messages'
import {
  appendText,
  appendThinking,
  initTool,
  addTool,
  appendToolOutput,
  completeTool,
  generateBlockId,
} from '@/utils/blocks'
import type { ContentBlock, MessageResponse } from '@/api/types'

interface UseSideChatReturn {
  /** Finalized blocks from the persisted history. */
  blocks: ContentBlock[]
  /** Live blocks accumulating in the current streaming turn. */
  currentBlocks: ContentBlock[]
  isWorking: boolean
  error: string | null
  sideChatId: string | null
  sendMessage: (content: string) => Promise<void>
  stopGeneration: () => Promise<void>
  /** Lazily create the side chat session (opens history + stream). */
  openSideChat: () => void
}

export function useSideChat(mainSessionId: string | null): UseSideChatReturn {
  const queryClient = useQueryClient()
  const [sideChatId, setSideChatId] = useState<string | null>(null)
  const [isWorking, setIsWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [currentBlocks, setCurrentBlocks] = useState<ContentBlock[]>([])
  const creatingRef = useRef<Promise<string | null> | null>(null)
  const streamAbortRef = useRef<AbortController | null>(null)

  // Reset when the main session changes — a side chat belongs to exactly one
  // source session.
  useEffect(() => {
    streamAbortRef.current?.abort()
    streamAbortRef.current = null
    setSideChatId(null)
    setIsWorking(false)
    setError(null)
    setCurrentBlocks([])
  }, [mainSessionId])

  // Create side chat session (lazily, deduplicated across concurrent callers)
  const ensureSideChat = useCallback(async (): Promise<string | null> => {
    if (sideChatId) return sideChatId
    if (!mainSessionId) return null
    if (!creatingRef.current) {
      creatingRef.current = createSideChat(mainSessionId)
        .then((result) => {
          setSideChatId(result.id)
          return result.id as string | null
        })
        .catch((err) => {
          setError(err instanceof Error ? err.message : 'Failed to create side chat')
          return null
        })
        .finally(() => {
          creatingRef.current = null
        })
    }
    return creatingRef.current
  }, [mainSessionId, sideChatId])

  // Fetch message history — same MessageResponse shape as the main chat
  // history endpoint, parsed through the shared block parser.
  const { data: rawMessages = [] } = useQuery({
    queryKey: ['sideChatMessages', sideChatId],
    queryFn: () => getSideChatMessages(mainSessionId!, sideChatId!),
    enabled: !!sideChatId && !!mainSessionId,
    refetchInterval: false,
  })

  const blocks = useMemo(() => parseTeamBlocks(rawMessages), [rawMessages])

  // Attach the SSE stream for a side chat session. Reducers are the shared
  // utils/blocks helpers, kept consistent with the main chat's sse-reducer
  // event schema (app/agent/schemas/events.py: `text`, `name`, `tool_call_id`,
  // `arguments`, `result`, `duration_ms`).
  const connectStream = useCallback(
    (sideId: string) => {
      if (!mainSessionId) return
      streamAbortRef.current?.abort()
      const abort = new AbortController()
      streamAbortRef.current = abort

      fetch(getSideChatStreamUrl(mainSessionId, sideId), { signal: abort.signal })
        .then((res) => {
          if (!res.ok) throw new Error(`SSE stream failed: ${res.status}`)
          readSSE(res, {
            onEvent: (type, data) => {
              if (abort.signal.aborted) return
              const d = data as Record<string, unknown>
              switch (type) {
                case 'agent_status':
                  // Replayed on mid-turn attach — restores the working flag
                  // after a page reload / panel reopen.
                  setIsWorking(d.status === 'working')
                  break
                case 'thinking':
                  setIsWorking(true)
                  setCurrentBlocks((prev) => appendThinking(prev, d.text as string))
                  break
                case 'message':
                  setIsWorking(true)
                  setCurrentBlocks((prev) => appendText(prev, d.text as string))
                  break
                case 'tool_call':
                  setIsWorking(true)
                  setCurrentBlocks((prev) =>
                    initTool(
                      prev,
                      d.name as string,
                      d.tool_call_id as string | undefined,
                      typeof d.duration_ms === 'number' ? d.duration_ms : undefined,
                    ),
                  )
                  break
                case 'tool_start':
                  setCurrentBlocks((prev) =>
                    addTool(
                      prev,
                      d.name as string,
                      d.arguments as string | undefined,
                      d.tool_call_id as string | undefined,
                      typeof d.duration_ms === 'number' ? d.duration_ms : undefined,
                    ),
                  )
                  break
                case 'tool_output_delta':
                  setCurrentBlocks((prev) =>
                    appendToolOutput(
                      prev,
                      d.name as string,
                      d.tool_call_id as string | undefined,
                      d.text as string,
                    ),
                  )
                  break
                case 'tool_end': {
                  const metadata = d.metadata as Record<string, unknown> | undefined
                  const durationMs =
                    typeof d.duration_ms === 'number'
                      ? d.duration_ms
                      : typeof metadata?.duration_ms === 'number'
                        ? metadata.duration_ms
                        : undefined
                  setCurrentBlocks((prev) =>
                    completeTool(
                      prev,
                      d.name as string,
                      d.tool_call_id as string | undefined,
                      d.result as string | undefined,
                      durationMs,
                    ),
                  )
                  break
                }
                case 'done':
                  // Finalize: history refetch replaces the live tail with the
                  // persisted blocks.
                  setIsWorking(false)
                  setCurrentBlocks([])
                  void queryClient.invalidateQueries({ queryKey: ['sideChatMessages', sideId] })
                  break
                case 'error':
                  setError((d.message as string) ?? 'Stream error')
                  setIsWorking(false)
                  break
              }
            },
            onError: (err) => {
              if (abort.signal.aborted || err.name === 'AbortError') return
              setError(err.message)
              setIsWorking(false)
            },
          })
        })
        .catch((err) => {
          if (abort.signal.aborted || err.name === 'AbortError') return
          setError(err.message)
          setIsWorking(false)
        })
    },
    [mainSessionId, queryClient],
  )

  // Attach once the session exists: no-op when no turn is active, mid-turn
  // replay when a run is still going (e.g. after a page reload).
  useEffect(() => {
    if (!sideChatId) return
    connectStream(sideChatId)
    return () => streamAbortRef.current?.abort()
  }, [sideChatId, connectStream])

  // Send message — POST starts the run; the stream attaches right after the
  // POST returns (same ordering as the main chat) and replays anything
  // emitted in between.
  const sendMessage = useCallback(
    async (content: string) => {
      if (!mainSessionId || !content.trim()) return

      const currentSideChatId = await ensureSideChat()
      if (!currentSideChatId) return

      setError(null)
      setIsWorking(true)
      setCurrentBlocks([])

      // Optimistically append the user message in MessageResponse shape so
      // parseTeamBlocks picks it up like any persisted message.
      const optimistic: MessageResponse = {
        id: `user-${generateBlockId()}`,
        session_id: currentSideChatId,
        role: 'user',
        content,
        reasoning_content: null,
        tool_calls: null,
        tool_call_id: null,
        name: null,
        is_summary: false,
        is_hidden: false,
        extra: null,
        created_at: new Date().toISOString(),
        attachments: null,
      }
      queryClient.setQueryData(
        ['sideChatMessages', currentSideChatId],
        // `old` is undefined the first time this key is written — the side
        // chat was just created and its history query may not have resolved
        // (or even started) yet.
        (old: MessageResponse[] | undefined) => [...(old ?? []), optimistic],
      )

      try {
        await sendSideChatMessage(mainSessionId, currentSideChatId, content)
        connectStream(currentSideChatId)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to send message')
        setIsWorking(false)
        // Roll the optimistic entry back to the persisted truth.
        void queryClient.invalidateQueries({ queryKey: ['sideChatMessages', currentSideChatId] })
      }
    },
    [mainSessionId, ensureSideChat, queryClient, connectStream],
  )

  // Stop — real backend interrupt (same mechanism as the main chat's
  // stopTeam), not just a client-side abort that leaves the agent running.
  const stopGeneration = useCallback(async () => {
    if (!sideChatId) return
    try {
      await postTeamChat(null, sideChatId, true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to stop generation')
    } finally {
      setIsWorking(false)
      setCurrentBlocks([])
      void queryClient.invalidateQueries({ queryKey: ['sideChatMessages', sideChatId] })
    }
  }, [sideChatId, queryClient])

  const openSideChat = useCallback(() => {
    void ensureSideChat()
  }, [ensureSideChat])

  return {
    blocks,
    currentBlocks,
    isWorking,
    error,
    sideChatId,
    sendMessage,
    stopGeneration,
    openSideChat,
  }
}
