/**
 * useSideChat — state management and API integration for the Side Chat panel.
 *
 * Owns:
 *   - Side chat session creation (lazily, on first message)
 *   - Message history fetching
 *   - Sending messages and streaming responses via SSE
 *   - Auto-scroll to bottom on new messages
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createSideChat, getSideChatMessages, sendSideChatMessage, getSideChatStreamUrl } from '@/api/client'
import { readSSE } from '@/api/sse'
import type { ContentBlock } from '@/api/types'

export interface SideChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  blocks: ContentBlock[]
  agent?: string | null
  timestamp: Date
}

interface UseSideChatReturn {
  messages: SideChatMessage[]
  isWorking: boolean
  error: string | null
  sideChatId: string | null
  sendMessage: (content: string) => Promise<void>
  openSideChat: () => void
  closeSideChat: () => void
}

export function useSideChat(mainSessionId: string | null): UseSideChatReturn {
  const queryClient = useQueryClient()
  const [sideChatId, setSideChatId] = useState<string | null>(null)
  const [isWorking, setIsWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [liveBlocks, setLiveBlocks] = useState<ContentBlock[]>([])
  const abortControllerRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  // Create side chat session (lazily)
  const createSideChatMutation = useCallback(async () => {
    if (!mainSessionId) return null
    try {
      const result = await createSideChat(mainSessionId)
      setSideChatId(result.side_chat_id)
      return result.side_chat_id
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create side chat')
      return null
    }
  }, [mainSessionId])

  // Fetch message history
  const { data: rawMessages = [] } = useQuery({
    queryKey: ['sideChatMessages', sideChatId],
    queryFn: () => getSideChatMessages(sideChatId!),
    enabled: !!sideChatId,
    refetchInterval: false,
  })

  // Transform raw messages to our format
  const messages: SideChatMessage[] = rawMessages.map((msg) => ({
    id: msg.id,
    role: msg.role,
    content: msg.content,
    blocks: (msg.blocks as unknown as ContentBlock[]) ?? [],
    agent: msg.agent ?? null,
    timestamp: msg.timestamp ? new Date(msg.timestamp) : new Date(),
  }))

  // Append live streaming blocks to the last assistant message or create new
  const allMessages = [...messages]
  if (liveBlocks.length > 0 && isWorking) {
    const lastMsg = allMessages[allMessages.length - 1]
    if (lastMsg && lastMsg.role === 'assistant') {
      lastMsg.blocks = [...lastMsg.blocks, ...liveBlocks]
    } else {
      allMessages.push({
        id: 'live',
        role: 'assistant',
        content: '',
        blocks: liveBlocks,
        timestamp: new Date(),
      })
    }
  }

  // Send message
  const sendMessage = useCallback(async (content: string) => {
    if (!mainSessionId || !content.trim()) return

    // Ensure side chat exists
    let currentSideChatId = sideChatId
    if (!currentSideChatId) {
      currentSideChatId = await createSideChatMutation()
      if (!currentSideChatId) return
    }

    setError(null)
    setIsWorking(true)
    setLiveBlocks([])

    // Abort any previous streaming request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }

    try {
      // Send message to backend
      await sendSideChatMessage(mainSessionId, currentSideChatId, content)

      // Optimistically add user message
      const userMessage: SideChatMessage = {
        id: `user-${Date.now()}`,
        role: 'user',
        content,
        blocks: [{ id: `user-block-${Date.now()}`, type: 'user', content }],
        timestamp: new Date(),
      }
      queryClient.setQueryData(
        ['sideChatMessages', currentSideChatId],
        (old: typeof rawMessages) => [...old, {
          id: userMessage.id,
          role: 'user',
          content,
          blocks: userMessage.blocks,
          timestamp: userMessage.timestamp.toISOString(),
        }],
      )

      // Start SSE stream for response
      abortControllerRef.current = new AbortController()
      const streamUrl = getSideChatStreamUrl(mainSessionId, currentSideChatId)

      fetch(streamUrl, { signal: abortControllerRef.current.signal })
        .then((res) => {
          if (!res.ok) throw new Error(`SSE stream failed: ${res.status}`)
          readSSE(res, {
            onEvent: (type, data) => {
              const d = data as Record<string, unknown>
              switch (type) {
                case 'message': {
                  const text = d.content as string
                  const blockId = d.block_id as string ?? `block-${Date.now()}`
                  setLiveBlocks((prev) => {
                    const last = prev[prev.length - 1]
                    if (last && last.type === 'text') {
                      return [...prev.slice(0, -1), { ...last, content: (last.content ?? '') + text }]
                    }
                    return [...prev, { id: blockId, type: 'text', content: text }]
                  })
                  break
                }
                case 'thinking': {
                  const text = d.content as string
                  setLiveBlocks((prev) => {
                    const last = prev[prev.length - 1]
                    if (last && last.type === 'thinking') {
                      return [...prev.slice(0, -1), { ...last, content: (last.content ?? '') + text }]
                    }
                    return [...prev, { id: `think-${Date.now()}`, type: 'thinking', content: text }]
                  })
                  break
                }
                case 'tool_call': {
                  const block: ContentBlock = {
                    id: (d.block_id as string) ?? `tool-${Date.now()}`,
                    type: 'tool',
                    content: d.summary as string ?? '',
                    toolName: d.tool_name as string,
                    toolArgs: d.tool_args as string,
                  }
                  setLiveBlocks((prev) => [...prev, block])
                  break
                }
                case 'tool_end': {
                  const blockId = d.block_id as string
                  setLiveBlocks((prev) =>
                    prev.map((b) =>
                      b.id === blockId ? { ...b, toolDone: true, toolResult: d.result as string } : b,
                    ),
                  )
                  break
                }
                case 'done': {
                  // Finalize: push live blocks into message history
                  setIsWorking(false)
                  setLiveBlocks([])
                  queryClient.invalidateQueries({ queryKey: ['sideChatMessages', currentSideChatId] })
                  break
                }
                case 'error': {
                  setError(d.message as string ?? 'Stream error')
                  setIsWorking(false)
                  setLiveBlocks([])
                  break
                }
              }
            },
            onError: (err) => {
              if (err.name !== 'AbortError') {
                setError(err.message)
                setIsWorking(false)
                setLiveBlocks([])
              }
            },
            onDone: () => {
              setIsWorking(false)
            },
          })
        })
        .catch((err) => {
          if (err.name !== 'AbortError') {
            setError(err.message)
            setIsWorking(false)
          }
        })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send message')
      setIsWorking(false)
    }
  }, [mainSessionId, sideChatId, createSideChatMutation, queryClient])

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [allMessages.length, liveBlocks.length])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort()
    }
  }, [])

  const openSideChat = useCallback(() => {
    if (!sideChatId && mainSessionId) {
      void createSideChatMutation()
    }
  }, [sideChatId, mainSessionId, createSideChatMutation])

  const closeSideChat = useCallback(() => {
    abortControllerRef.current?.abort()
    setSideChatId(null)
    setLiveBlocks([])
    setIsWorking(false)
    setError(null)
  }, [])

  return {
    messages: allMessages,
    isWorking,
    error,
    sideChatId,
    sendMessage,
    openSideChat,
    closeSideChat,
  }
}
