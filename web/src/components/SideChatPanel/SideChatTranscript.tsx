/**
 * SideChatTranscript — message list for the Side Chat panel.
 *
 * Renders `blocks` (finalized history) + `currentBlocks` (live streaming tail)
 * through the exact same pipeline as the main chat's AgentView:
 * `partitionTurns` → `BlockRenderer` (+ `groupConsecutiveToolCalls` for
 * finished turns) → `AssistantTurnFooter`. Narrow-panel differences only:
 * no turn windowing, no chapters, no revert, compact footers.
 */
import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { ChevronDown } from 'lucide-react'
import EvoFluxLogo from '@/assets/brand/evoflux-app-icon.png'
import { BlockRenderer } from '../BlockRenderer'
import { AssistantTurnFooter } from '../AssistantTurnFooter'
import { groupConsecutiveToolCalls, ToolCallGroupCard } from '../ToolCallGroup'
import type { ToolBlockGroup } from '../ToolCallGroup'
import { LoadingVerb } from '../motion/LoadingVerb'
import { partitionTurns, type TurnItem } from '@/utils/turns'
import type { ContentBlock } from '@/api/types'

const SCROLL_THRESHOLD = 40

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
  const pinnedRef = useRef(true)
  const [showScrollBtn, setShowScrollBtn] = useState(false)

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

  const scrollToBottom = useCallback((smooth = false) => {
    const el = scrollRef.current
    if (!el) return
    pinnedRef.current = true
    setShowScrollBtn(false)
    if (smooth) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    } else {
      el.scrollTop = el.scrollHeight
    }
  }, [])

  // Track the pinned state from user scrolls.
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const onScroll = () => {
      const atBottom = isAtBottom()
      pinnedRef.current = atBottom
      setShowScrollBtn((prev) => (prev === !atBottom ? prev : !atBottom))
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [isAtBottom])

  // Auto-scroll while pinned — block count or last block text changed.
  const lastContent =
    currentBlocks[currentBlocks.length - 1]?.content ??
    blocks[blocks.length - 1]?.content ??
    ''
  const totalLen = blocks.length + currentBlocks.length
  useEffect(() => {
    if (pinnedRef.current) scrollToBottom()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [totalLen, lastContent])

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-3 py-4">
        {isEmpty ? (
          emptyState ?? null
        ) : (
          <div className="space-y-6">
            {turnItems.map((item, k) => {
              if (item.kind === 'user') {
                return (
                  <BlockRenderer
                    key={item.block.id}
                    block={item.block}
                    isStreaming={false}
                    sessionId={sessionId}
                    renderLeadingQuoteAsContext
                  />
                )
              }
              const isTrailingTurn = k === turnItems.length - 1
              const turnIsStreaming = isWorking && isTrailingTurn
              // Don't collapse the live streaming turn — keep per-tool cards
              // visible so the panel shows real-time activity.
              const groupedBlocks = turnIsStreaming
                ? item.blocks
                : groupConsecutiveToolCalls(item.blocks)
              const blockAbsIdx = new Map(item.blocks.map((b, j) => [b.id, item.startIndex + j]))
              return (
                <div key={`turn-${item.startIndex}-${item.blocks[0]?.id ?? k}`}>
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
                          />
                        )
                      }
                      const block = renderItem as ContentBlock
                      const absIdx = blockAbsIdx.get(block.id) ?? item.startIndex + j
                      const isStreaming = isWorking && absIdx >= blocks.length
                      return (
                        <div key={block.id} className={isStreaming ? 'block-reveal' : undefined}>
                          <BlockRenderer
                            block={block}
                            isStreaming={isStreaming}
                            sessionId={sessionId}
                          />
                        </div>
                      )
                    })}
                    {!turnIsStreaming && (
                      <AssistantTurnFooter turnBlocks={item.blocks} size="compact" />
                    )}
                  </div>
                </div>
              )
            })}

            {/* Loading verb while the agent has been triggered but produced
             * no content yet — covers the POST → first SSE event gap. */}
            {isWorking && currentBlocks.length === 0 && (
              <div>
                <div className="mb-2 flex items-center gap-1.5">
                  <img src={EvoFluxLogo} width={14} height={14} className="rounded-xs opacity-70" alt="" aria-hidden="true" />
                  <span className="text-xs font-medium text-(--color-text-muted)">{agentLabel}</span>
                </div>
                <LoadingVerb className="py-1 pl-0.5" />
              </div>
            )}
          </div>
        )}
      </div>

      {showScrollBtn && !isEmpty && (
        <button
          onClick={() => scrollToBottom(true)}
          className="absolute bottom-3 left-1/2 z-(--z-panel) -translate-x-1/2 rounded-full border border-(--color-border) bg-(--bg-card) p-1 text-(--color-text-muted) transition-colors hover:text-(--color-text-2)"
          aria-label="Scroll to bottom"
        >
          <ChevronDown size={16} />
        </button>
      )}
    </div>
  )
}
