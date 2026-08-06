/**
 * SideChatTranscript — message list for the Side Chat panel.
 *
 * Renders `blocks` (finalized history) + `currentBlocks` (live streaming tail)
 * through the exact same pipeline as the main chat's AgentView:
 * `partitionTurns` → `BlockRenderer` (+ `groupConsecutiveToolCalls` for
 * finished turns) → `AssistantTurnFooter`. Narrow-panel differences only:
 * no turn windowing, no revert, compact footers.
 */
import { useMemo } from 'react'
import { ChevronDown } from 'lucide-react'
import EvoFluxLogo from '@/assets/brand/evoflux-app-icon.png'
import { BlockRenderer } from '../BlockRenderer'
import { AssistantTurnFooter } from '../AssistantTurnFooter'
import { groupConsecutiveToolCalls, ToolCallGroupCard } from '../ToolCallGroup'
import type { ToolBlockGroup } from '../ToolCallGroup'
import { ActivityStatus } from '../motion/ActivityStatus'
import { BlockEnter } from '../motion/BlockEnter'
import { isLatestStreamingItem, partitionTurns, type TurnItem } from '@/utils/turns'
import { latestMCPAppResourceBlockIds } from '@/utils/mcp-app-artifacts'
import { latestDirectUserBlockId } from '@/utils/blocks'
import { usePinnedTranscript } from '@/hooks/usePinnedTranscript'
import type { ContentBlock } from '@/api/types'

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

  // `BlockRenderer` only mounts the interactive MCP app for ids in this set, so
  // without it Side Chat silently downgraded every app resource to a raw tool
  // result. Reduce to a primitive key first: the concatenated blocks are a new
  // array per streamed chunk, and a fresh Set would break the renderers' memo.
  const latestMCPAppBlockIdsKey = useMemo(
    () => [...latestMCPAppResourceBlockIds([...blocks, ...currentBlocks])].sort().join('\u0000'),
    [blocks, currentBlocks],
  )
  const latestMCPAppBlockIds = useMemo(
    () => new Set(latestMCPAppBlockIdsKey ? latestMCPAppBlockIdsKey.split('\u0000') : []),
    [latestMCPAppBlockIdsKey],
  )

  const isEmpty = blocks.length === 0 && currentBlocks.length === 0 && !isWorking
  const totalLen = blocks.length + currentBlocks.length
  const latestLiveUserBlockId = useMemo(
    () => latestDirectUserBlockId(currentBlocks),
    [currentBlocks],
  )
  const {
    contentRef,
    scrollRef,
    scrollToBottom,
    showScrollButton: showScrollBtn,
  } = usePinnedTranscript({
    isEmpty,
    contentKey: totalLen,
    resetKey: sessionId,
    followKey: latestLiveUserBlockId,
  })

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
                          <BlockEnter key={(renderItem as ToolBlockGroup).id}>
                            <ToolCallGroupCard
                              group={renderItem as ToolBlockGroup}
                              isStreaming={isLatestStreamingItem(turnIsStreaming, j, groupedBlocks.length)}
                              sessionId={sessionId}
                              latestMCPAppBlockIds={latestMCPAppBlockIds}
                            />
                          </BlockEnter>
                        )
                      }
                      const block = renderItem as ContentBlock
                      // Keep completed phases still; only the latest visible
                      // item in the active turn is actually streaming.
                      const isStreaming = isLatestStreamingItem(turnIsStreaming, j, groupedBlocks.length)
                      return (
                        <BlockEnter key={block.id} disabled={isStreaming && block.type === 'text'}>
                          <BlockRenderer
                            block={block}
                            isStreaming={isStreaming}
                            sessionId={sessionId}
                            latestMCPAppBlockIds={latestMCPAppBlockIds}
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
