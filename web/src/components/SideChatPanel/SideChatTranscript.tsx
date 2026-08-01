/**
 * SideChatTranscript — message list for the Side Chat panel.
 *
 * Renders `blocks` (finalized history) + `currentBlocks` (live streaming tail)
 * through the exact same pipeline as the main chat's AgentView:
 * `partitionTurns` → `BlockRenderer` (+ `groupConsecutiveToolCalls` for
 * finished turns) → `AssistantTurnFooter`. Narrow-panel differences only:
 * no turn windowing, no revert, compact footers.
 */
import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { ChevronDown } from 'lucide-react'
import EvoFluxLogo from '@/assets/brand/evoflux-app-icon.png'
import { BlockRenderer } from '../BlockRenderer'
import { AssistantTurnFooter } from '../AssistantTurnFooter'
import { groupConsecutiveToolCalls, ToolCallGroupCard } from '../ToolCallGroup'
import type { ToolBlockGroup } from '../ToolCallGroup'
import { ActivityStatus } from '../motion/ActivityStatus'
import { BlockEnter } from '../motion/BlockEnter'
import { partitionTurns, type TurnItem } from '@/utils/turns'
import type { ContentBlock } from '@/api/types'

const SCROLL_THRESHOLD = 40
const USER_SCROLL_DETACH_DELTA = 4

interface SideChatTranscriptProps {
  /** Finalized blocks from the persisted history. */
  blocks: ContentBlock[]
  /** Live blocks accumulating in the current streaming turn. */
  currentBlocks: ContentBlock[]
  isWorking: boolean
  /** Session id used by markdown/link renderers inside blocks. */
  sessionId?: string
  /** Agent name shown above assistant turns. */
  agentLabel?: string
  /** Rendered when there are no messages yet. */
  emptyState?: React.ReactNode
}

export function SideChatTranscript({
  blocks,
  currentBlocks,
  isWorking,
  sessionId,
  agentLabel = 'evoflux',
  emptyState,
}: SideChatTranscriptProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const pinnedRef = useRef(true)
  const [showScrollBtn, setShowScrollBtn] = useState(false)
  const showScrollBtnRef = useRef(false)

  // Merge finalized turns with the live tail — a trailing finalized assistant
  // turn and a leading live assistant run are one contiguous turn (same rule
  // as AgentView).
  const turnItems = useMemo(() => {
    const finalized = partitionTurns(blocks)
    if (currentBlocks.length === 0) return finalized
    const offset = blocks.length
    const live = partitionTurns(currentBlocks).map((item): TurnItem =>
      item.kind === 'user'
        ? { ...item, index: item.index + offset }
        : { ...item, startIndex: item.startIndex + offset },
    )
    const lastFinalized = finalized[finalized.length - 1]
    const firstLive = live[0]
    if (lastFinalized?.kind === 'assistant' && firstLive?.kind === 'assistant') {
      return [
        ...finalized.slice(0, -1),
        {
          kind: 'assistant' as const,
          blocks: [...lastFinalized.blocks, ...firstLive.blocks],
          startIndex: lastFinalized.startIndex,
        },
        ...live.slice(1),
      ]
    }
    return [...finalized, ...live]
  }, [blocks, currentBlocks])

  const isEmpty = blocks.length === 0 && currentBlocks.length === 0 && !isWorking

  const isAtBottom = useCallback(() => {
    const el = scrollRef.current
    if (!el) return true
    return el.scrollHeight - el.scrollTop - el.clientHeight <= SCROLL_THRESHOLD
  }, [])

  const setScrollButtonVisible = useCallback((visible: boolean) => {
    if (showScrollBtnRef.current === visible) return
    showScrollBtnRef.current = visible
    setShowScrollBtn(visible)
  }, [])

  const scrollToBottom = useCallback((smooth = false) => {
    const el = scrollRef.current
    if (!el) return
    pinnedRef.current = true
    setScrollButtonVisible(false)
    if (smooth) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    } else {
      el.scrollTop = el.scrollHeight
    }
  }, [setScrollButtonVisible])

  // Track the pinned state from user scrolls.
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    let scrollFrame: number | null = null
    const onScroll = () => {
      if (scrollFrame !== null) return
      scrollFrame = requestAnimationFrame(() => {
        scrollFrame = null
        const atBottom = isAtBottom()
        pinnedRef.current = atBottom
        setScrollButtonVisible(!atBottom)
      })
    }
    const onWheel = (event: WheelEvent) => {
      if (event.deltaY < -USER_SCROLL_DETACH_DELTA) {
        pinnedRef.current = false
        setScrollButtonVisible(true)
      }
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    el.addEventListener('wheel', onWheel, { passive: true })
    return () => {
      if (scrollFrame !== null) cancelAnimationFrame(scrollFrame)
      el.removeEventListener('scroll', onScroll)
      el.removeEventListener('wheel', onWheel)
    }
  }, [isAtBottom, setScrollButtonVisible])

  const totalLen = blocks.length + currentBlocks.length

  // Track the visible transcript rather than the raw stream. This keeps the
  // narrow panel pinned at exactly the same cadence as Markdown is revealed.
  useEffect(() => {
    const content = contentRef.current
    if (!content || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => {
      const el = scrollRef.current
      if (el && pinnedRef.current) el.scrollTop = el.scrollHeight
    })
    observer.observe(content)
    return () => observer.disconnect()
  }, [isEmpty])

  useEffect(() => {
    const el = scrollRef.current
    if (el && pinnedRef.current) el.scrollTop = el.scrollHeight
  }, [totalLen])

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div
        ref={scrollRef}
        data-testid="side-chat-scroll"
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 py-4"
      >
        {isEmpty ? (
          emptyState ?? null
        ) : (
          <div ref={contentRef} className="space-y-6">
            {turnItems.map((item, k) => {
              if (item.kind === 'user') {
                return (
                  <div key={item.block.id} className="oa-transcript-turn">
                    <BlockRenderer
                      block={item.block}
                      isStreaming={false}
                      sessionId={sessionId}
                      renderLeadingQuoteAsContext
                    />
                  </div>
                )
              }
              const isTrailingTurn = k === turnItems.length - 1
              const turnIsStreaming = isWorking && isTrailingTurn
              const groupedBlocks = groupConsecutiveToolCalls(item.blocks)
              const blockAbsIdx = new Map(item.blocks.map((b, j) => [b.id, item.startIndex + j]))
              return (
                <div
                  key={`turn-${item.startIndex}-${item.blocks[0]?.id ?? k}`}
                  className={turnIsStreaming ? undefined : 'oa-transcript-turn'}
                >
                  <div className="mb-2 flex items-center gap-1.5">
                    <img src={EvoFluxLogo} width={14} height={14} className="rounded-xs opacity-70" alt="" aria-hidden="true" />
                    <span className="text-xs font-medium text-(--color-text-muted)">{agentLabel}</span>
                  </div>
                  <div className="space-y-2">
                    {groupedBlocks.map((renderItem, j) => {
                      if ('kind' in renderItem && (renderItem as ToolBlockGroup).kind === 'group') {
                        return (
                          <ToolCallGroupCard
                            key={`group-${item.startIndex}-${j}`}
                            group={renderItem as ToolBlockGroup}
                            isStreaming={turnIsStreaming}
                            sessionId={sessionId}
                          />
                        )
                      }
                      const block = renderItem as ContentBlock
                      const absIdx = blockAbsIdx.get(block.id) ?? item.startIndex + j
                      const isStreaming = isWorking && absIdx >= blocks.length
                      return (
                        <BlockEnter key={block.id} disabled={isStreaming && block.type === 'text'}>
                          <BlockRenderer
                            block={block}
                            isStreaming={isStreaming}
                            sessionId={sessionId}
                          />
                        </BlockEnter>
                      )
                    })}
                    {!turnIsStreaming && (
                      <AssistantTurnFooter turnBlocks={item.blocks} size="compact" />
                    )}
                  </div>
                </div>
              )
            })}

            {/* Stable activity state while the agent has been triggered but produced
             * no content yet — covers the POST → first SSE event gap. */}
            {isWorking && currentBlocks.length === 0 && (
              <div>
                <div className="mb-2 flex items-center gap-1.5">
                  <img src={EvoFluxLogo} width={14} height={14} className="rounded-xs opacity-70" alt="" aria-hidden="true" />
                  <span className="text-xs font-medium text-(--color-text-muted)">{agentLabel}</span>
                </div>
                <ActivityStatus className="py-1 pl-0.5 text-xs" />
              </div>
            )}
          </div>
        )}
      </div>

      {showScrollBtn && !isEmpty && (
        <button
          onClick={() => scrollToBottom(true)}
          className="absolute right-3 bottom-3 z-(--z-panel) flex size-8 items-center justify-center rounded-full border border-(--color-border) bg-(--bg-card)/95 text-(--color-text-muted) shadow-md backdrop-blur transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
          aria-label="Back to latest message"
          title="Back to latest message"
        >
          <ChevronDown size={16} />
        </button>
      )}
    </div>
  )
}
