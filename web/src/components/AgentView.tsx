/**
 * AgentView — single-agent full-width view (viewMode === 'agent').
 *
 * Renders a flat ContentBlock[] stream (finalized + live) with:
 * - type:'user'    → yellow user bubble
 * - type:'thinking' → collapsible thinking block
 * - type:'tool'    → tool call card
 * - type:'text'    → markdown prose
 *
 * Per-block rendering is delegated to the shared `BlockRenderer`
 * (see `BlockRenderer.tsx`, also used by the Side Chat panel).
 *
 * Blocks are grouped into "turns" via `partitionTurns` (see `utils/turns.ts`):
 * a turn is a contiguous run of non-user blocks. Each finalized turn renders a
 * single `AssistantTurnFooter` (copy + timestamp); only the trailing turn hides
 * its footer while the agent is actively streaming. The same shared
 * `AssistantTurn` component (see `AssistantTurnFooter.tsx`) is used by
 * `AgentPane` for split/unified modes.
 */

import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { ChatWelcome } from './ChatWelcome'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { BlockRenderer } from './BlockRenderer'
import { AssistantTurnFooter } from './AssistantTurnFooter'
import { groupConsecutiveToolCalls, ToolCallGroupCard } from './ToolCallGroup'
import type { ToolBlockGroup } from './ToolCallGroup'
import { PendingMessageQueue } from './PendingMessageQueue'
import { getVisibleTurnWindow, isLatestStreamingItem, partitionTurns, type TurnItem } from '@/utils/turns'
import { isDirectUserBlock, latestDirectUserBlockId } from '@/utils/blocks'
import { buildUserMessageNavigationItems } from '@/utils/user-message-navigation'
import { mcpAppResourceUri } from '@/utils/mcp-app-artifacts'
import { usePinnedTranscript } from '@/hooks/usePinnedTranscript'
import { cn } from '@/lib/utils'
import { useTeamStore } from '@/stores/useTeamStore'
import { ActivityStatus } from './motion/ActivityStatus'
import { BlockEnter } from './motion/BlockEnter'
import { TextSelectionAction } from './TextSelectionAction'
import { TurnChangesCard } from './TurnChangesCard'
import { UserMessageNavigationRail } from './UserMessageNavigationRail'
import { StreamingTurnHeader } from './StreamingTurnHeader'
import type { ContentBlock, TurnChangesPending } from '@/api/types'

const LOAD_OLDER_THRESHOLD = 300
const INITIAL_RENDERED_TURNS = 48
const TURN_RENDER_STEP = 48

function findUserMessageNavigationAnchor(
  container: HTMLDivElement,
  messageId: string,
): HTMLElement | null {
  for (const element of container.querySelectorAll<HTMLElement>(
    '[data-user-message-navigation-anchor]',
  )) {
    if (element.dataset.userMessageNavigationAnchor === messageId) return element
  }
  return null
}

interface AgentViewProps {
  /** Finalized blocks from previous turns. */
  blocks: ContentBlock[]
  /** Live blocks accumulating in the current turn. */
  currentBlocks: ContentBlock[]
  /** True while the agent is actively streaming. */
  isWorking: boolean
  /** True when the agent is in error state. */
  isError?: boolean
  /** Error message to display when isError is true. */
  lastError?: string | null
  /** True while this turn was started by /continue. */
  isContinuing?: boolean
  /** Continue from the trailing assistant turn. */
  onContinue?: () => void
  /** Optional slot rendered in place of the default mascot empty state. */
  emptyState?: React.ReactNode
  /** Quote selected transcript text into the primary composer. */
  onAddSelectionToChat?: (selectedText: string) => void
  /** Prepare a primary-chat prompt requesting more detail about selected text. */
  onRequestSelectionDetails?: (selectedText: string) => void
  /** Open a side-chat thread grounded in selected transcript text. */
  onSendToSideChat?: (selectedText: string) => void
  /** Latest completed turn changes, shown only by Coding mode for the lead. */
  turnChanges?: TurnChangesPending | null
}

export function AgentView({ blocks, currentBlocks, isWorking, isError, lastError, isContinuing = false, onContinue, emptyState, onAddSelectionToChat, onRequestSelectionDetails, onSendToSideChat, turnChanges }: AgentViewProps) {
  const [renderedTurnCount, setRenderedTurnCount] = useState(INITIAL_RENDERED_TURNS)
  const sessionId = useTeamStore((s) => s.sessionId) ?? undefined
  const prevScrollHeightRef = useRef<number | null>(null)
  const pendingRestoreRef = useRef(false)
  const pendingUserNavigationRef = useRef<{
    messageId: string
    behavior: ScrollBehavior
  } | null>(null)
  // Me mirror store _loadingOlder in a ref so the wheel handler can check
  // it synchronously without subscribing to store state changes.
  const loadingOlderRef = useRef(false)
  const topLoadArmedRef = useRef(true)

  const handleRevert = useCallback(() => {
    void useTeamStore.getState().undoTeam()
  }, [])

  // Me: everything derived from the finalized ``blocks`` prop is memoized on
  // [blocks] only (stable between SSE chunks); the live ``currentBlocks``
  // tail — a fresh array on every streamed token — is merged in a cheap
  // final step so per-chunk work is O(current turn), not O(whole history).
  const totalLen = blocks.length + currentBlocks.length

  const finalizedVisibleCount = useMemo(
    () => blocks.reduce((n, block) => (block.type === 'compaction' ? n : n + 1), 0),
    [blocks],
  )
  const visibleCount =
    finalizedVisibleCount +
    currentBlocks.reduce((n, block) => (block.type === 'compaction' ? n : n + 1), 0)

  const finalizedLatestUserBlockId = useMemo(() => latestDirectUserBlockId(blocks), [blocks])
  const latestUserBlockId = useMemo(
    () => latestDirectUserBlockId(currentBlocks) ?? finalizedLatestUserBlockId,
    [currentBlocks, finalizedLatestUserBlockId],
  )

  const finalizedTurnItems = useMemo(() => partitionTurns(blocks), [blocks])
  const turnItems = useMemo(() => {
    if (currentBlocks.length === 0) return finalizedTurnItems
    const offset = blocks.length
    const liveTurnItems = partitionTurns(currentBlocks).map((item): TurnItem =>
      item.kind === 'user'
        ? { ...item, index: item.index + offset }
        : { ...item, startIndex: item.startIndex + offset },
    )
    const lastFinalized = finalizedTurnItems[finalizedTurnItems.length - 1]
    const firstLive = liveTurnItems[0]
    // A trailing finalized assistant turn and a leading live assistant run
    // are one contiguous turn — merge them so keys/footers match what a
    // full partition of the merged block list would produce.
    if (lastFinalized?.kind === 'assistant' && firstLive?.kind === 'assistant') {
      return [
        ...finalizedTurnItems.slice(0, -1),
        {
          kind: 'assistant' as const,
          blocks: [...lastFinalized.blocks, ...firstLive.blocks],
          startIndex: lastFinalized.startIndex,
        },
        ...liveTurnItems.slice(1),
      ]
    }
    return [...finalizedTurnItems, ...liveTurnItems]
  }, [blocks.length, currentBlocks, finalizedTurnItems])
  const { hiddenTurnCount, visibleTurnItems } = useMemo(
    () => getVisibleTurnWindow(turnItems, renderedTurnCount),
    [renderedTurnCount, turnItems],
  )
  const userMessageNavigationItems = useMemo(
    () => buildUserMessageNavigationItems(turnItems),
    [turnItems],
  )
  const userMessageNavigationIds = useMemo(
    () => new Set(userMessageNavigationItems.map((item) => item.id)),
    [userMessageNavigationItems],
  )

  const finalizedMCPAppIdsByUri = useMemo(() => {
    const byUri = new Map<string, string>()
    for (const block of blocks) {
      if (block.type !== 'tool' || !block.toolDone) continue
      const uri = mcpAppResourceUri(block)
      if (uri) byUri.set(uri, block.id)
    }
    return byUri
  }, [blocks])
  const latestMCPAppBlockIdsKey = useMemo(() => {
    let byUri = finalizedMCPAppIdsByUri
    if (currentBlocks.length > 0) {
      byUri = new Map(finalizedMCPAppIdsByUri)
      for (const block of currentBlocks) {
        if (block.type !== 'tool' || !block.toolDone) continue
        const uri = mcpAppResourceUri(block)
        if (uri) byUri.set(uri, block.id)
      }
    }
    return [...byUri.values()].join('\0')
  }, [currentBlocks, finalizedMCPAppIdsByUri])
  // Key the Set by its primitive contents so streamed text chunks retain the
  // same identity until an MCP app resource actually changes.
  const latestMCPAppBlockIds = useMemo(
    () => new Set(latestMCPAppBlockIdsKey ? latestMCPAppBlockIdsKey.split('\0') : []),
    [latestMCPAppBlockIdsKey],
  )
  const latestLiveUserBlockId = useMemo(
    () => latestDirectUserBlockId(currentBlocks),
    [currentBlocks],
  )

  const handleViewportScroll = useCallback((element: HTMLDivElement) => {
    if (element.scrollTop > LOAD_OLDER_THRESHOLD * 2) {
      topLoadArmedRef.current = true
      return
    }
    if (element.scrollTop > LOAD_OLDER_THRESHOLD || !topLoadArmedRef.current) return

    topLoadArmedRef.current = false
    if (hiddenTurnCount > 0) {
      prevScrollHeightRef.current = element.scrollHeight
      pendingRestoreRef.current = true
      setRenderedTurnCount((count) => Math.min(turnItems.length, count + TURN_RENDER_STEP))
      return
    }
    if (!useTeamStore.getState().hasMore || loadingOlderRef.current) return

    loadingOlderRef.current = true
    prevScrollHeightRef.current = element.scrollHeight
    pendingRestoreRef.current = true
    void useTeamStore.getState().loadOlderMessages().finally(() => {
      loadingOlderRef.current = false
    })
  }, [hiddenTurnCount, turnItems.length])

  const isEmpty = visibleCount === 0 && !isWorking
  const {
    contentRef,
    detach: detachFromBottom,
    restorePrependOffset,
    scrollRef,
    scrollToBottom,
    showScrollButton: showScrollBtn,
  } = usePinnedTranscript({
    isEmpty,
    contentKey: totalLen,
    resetKey: sessionId,
    followKey: latestLiveUserBlockId ?? (isWorking && isContinuing ? `continue:${sessionId ?? ''}` : null),
    onScrollFrame: handleViewportScroll,
  })

  const showEarlierTurns = useCallback(() => {
    const element = scrollRef.current
    if (element) {
      prevScrollHeightRef.current = element.scrollHeight
      pendingRestoreRef.current = true
    }
    setRenderedTurnCount((count) => Math.min(turnItems.length, count + TURN_RENDER_STEP))
  }, [scrollRef, turnItems.length])

  const scrollToUserMessage = useCallback((
    messageId: string,
    behavior: ScrollBehavior,
  ) => {
    const container = scrollRef.current
    const item = userMessageNavigationItems.find((entry) => entry.id === messageId)
    if (!container || !item) return

    detachFromBottom()

    const anchor = findUserMessageNavigationAnchor(container, messageId)
    if (anchor) {
      anchor.scrollIntoView({ behavior, block: 'start' })
      return
    }

    // The rail indexes every loaded prompt, including turns outside the
    // transcript's render window. Reveal just enough history to mount the
    // target, then complete the navigation in the effect below.
    pendingUserNavigationRef.current = { messageId, behavior }
    const requiredTurnCount = turnItems.length - item.turnIndex
    setRenderedTurnCount((count) => Math.max(count, requiredTurnCount))
  }, [detachFromBottom, scrollRef, turnItems.length, userMessageNavigationItems])

  // Me restore scroll position after older messages are prepended.
  // We track a "pending restore" flag separately from blocks.length so
  // that SSE flushes (which also grow blocks) never accidentally trigger
  // a scroll-position restore.
  useEffect(() => {
    if (!pendingRestoreRef.current || prevScrollHeightRef.current === null) return
    pendingRestoreRef.current = false
    restorePrependOffset(prevScrollHeightRef.current)
    prevScrollHeightRef.current = null
  }, [blocks.length, renderedTurnCount, restorePrependOffset])

  useEffect(() => {
    const pending = pendingUserNavigationRef.current
    const container = scrollRef.current
    if (!pending || !container) return
    const anchor = findUserMessageNavigationAnchor(container, pending.messageId)
    if (!anchor) return
    pendingUserNavigationRef.current = null
    anchor.scrollIntoView({ behavior: pending.behavior, block: 'start' })
  }, [blocks.length, renderedTurnCount, scrollRef, visibleTurnItems])

  return (
    <div className="@container/agent-view relative flex min-h-0 flex-1 flex-col">
    <div ref={scrollRef} className="flex flex-1 flex-col overflow-y-auto overscroll-contain">
      <div
        ref={contentRef}
        className={cn(
          'mx-auto w-full max-w-4xl px-3 py-4',
          isEmpty && 'flex flex-1 flex-col items-center justify-center',
        )}
      >
        {isEmpty && (
           emptyState ?? <ChatWelcome />
         )}

         <div className="space-y-4">
              {hiddenTurnCount > 0 && (
                <div className="flex justify-center py-2">
                  <button
                    type="button"
                    onClick={showEarlierTurns}
                    className="inline-flex min-h-10 items-center gap-1 rounded-full border border-(--color-border) bg-(--bg-card) px-3 py-1.5 text-xs text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:ring-2 focus-visible:ring-(--focus-ring) focus-visible:outline-none"
                    aria-label={`Show ${Math.min(TURN_RENDER_STEP, hiddenTurnCount)} earlier turns`}
                  >
                    <ChevronUp size={13} aria-hidden="true" />
                    Show earlier messages · {hiddenTurnCount} hidden
                  </button>
                </div>
              )}
              {visibleTurnItems.map((item, k) => {
                 const globalTurnIndex = hiddenTurnCount + k
                 if (item.kind === 'user') {
                   const navigationItem = userMessageNavigationIds.has(item.block.id)
                   return (
                     <div
                       key={item.block.id}
                       className="oa-transcript-turn"
                       data-user-message-navigation-anchor={navigationItem ? item.block.id : undefined}
                     >
                       <BlockRenderer
                         block={item.block}
                         isStreaming={false}
                         sessionId={sessionId}
                         onRevert={item.block.id === latestUserBlockId ? handleRevert : undefined}
                         latestMCPAppBlockIds={latestMCPAppBlockIds}
                         renderLeadingQuoteAsContext
                       />
                     </div>
                   )
                 }
                 // Me only the trailing turn (no user block after) can be "live"
                  const isTrailingTurn = globalTurnIndex === turnItems.length - 1
                  const turnIsStreaming = isWorking && isTrailingTurn
                  const canContinue = isTrailingTurn && !isWorking ? onContinue : undefined
                  const groupedBlocks = groupConsecutiveToolCalls(item.blocks)
                  const turnStartedAt = item.blocks.find((block) => block.startedAt)?.startedAt
                 return (
                   <div
                     key={`turn-${item.startIndex}-${item.blocks[0]?.id ?? k}`}
                     className={turnIsStreaming ? 'oa-active-turn-runway' : 'oa-transcript-turn'}
                   >
                     {turnIsStreaming && <StreamingTurnHeader startedAt={turnStartedAt} />}
                     <div className="space-y-2">
                       {groupedBlocks.map((renderItem, j) => {
                         if ('kind' in renderItem && (renderItem as ToolBlockGroup).kind === 'group') {
                           return (
                             <ToolCallGroupCard
                               key={(renderItem as ToolBlockGroup).id}
                               group={renderItem as ToolBlockGroup}
                               isStreaming={isLatestStreamingItem(turnIsStreaming, j, groupedBlocks.length)}
                               sessionId={sessionId}
                               latestMCPAppBlockIds={latestMCPAppBlockIds}
                             />
                           )
                         }
                         const block = renderItem as ContentBlock
                         // A live turn can already contain several completed
                         // thinking/tool phases. Only its newest visible item
                         // should retain the streaming animation.
                         const isStreaming = isLatestStreamingItem(turnIsStreaming, j, groupedBlocks.length)
                         return (
                           <BlockEnter key={block.id} disabled={isStreaming && block.type === 'text'}>
                             <BlockRenderer
                               block={block}
                               isStreaming={isStreaming}
                               sessionId={sessionId}
                               onRevert={isDirectUserBlock(block) && block.id === latestUserBlockId ? handleRevert : undefined}
                               latestMCPAppBlockIds={latestMCPAppBlockIds}
                             />
                           </BlockEnter>
                         )
                       })}
                       {!turnIsStreaming && (
                         <AssistantTurnFooter
                           turnBlocks={item.blocks}
                           size="roomy"
                           onContinue={canContinue}
                         />
                       )}
                       {!isWorking
                         && globalTurnIndex === turnItems.length - 1
                         && turnChanges
                         && turnChanges.files.length > 0
                         && turnChanges.sessionId === sessionId && (
                         <TurnChangesCard changes={turnChanges} />
                       )}
                     </div>
                   </div>
                 )
                })}

            {/* Show a stable activity state when:
             *   1. pending — user just sent, agent hasn't woken yet (no agent_status event yet), OR
             *   2. working with no agent content yet (user bubbles don't count).
             * Covers the POST → first SSE event gap so the user always gets immediate feedback.
             *
             * Note: `[].every()` returns true, so the working branch must
             * also require a non-empty currentBlocks list — otherwise the
             * indicator sticks around after `done` flushes the buffer if a
             * stale `working` status briefly survives.
             */}
            {((!isWorking && !isError && currentBlocks.some(isDirectUserBlock)) ||
              (isWorking && (
                (isContinuing && currentBlocks.length === 0) ||
                (currentBlocks.length > 0 && currentBlocks.every((b) => b.type === 'user'))
              ))) && (
              <div className="oa-active-turn-runway">
                <ActivityStatus className="py-1 pl-0.5 text-xs" />
              </div>
            )}

            <PendingMessageQueue />

            {isError && lastError && (
             <div className="mt-3 rounded-lg border border-(--color-error) bg-(--color-error-subtle) px-3 py-2">
               <p className="text-xs text-(--color-error)">{lastError}</p>
             </div>
           )}

         </div>
      </div>
    </div>
    <UserMessageNavigationRail
      items={userMessageNavigationItems}
      containerRef={scrollRef}
      isWorking={isWorking}
      onNavigate={scrollToUserMessage}
    />
    {showScrollBtn && !isEmpty && (
      <div className="pointer-events-none absolute inset-x-0 bottom-3 z-(--z-panel) mx-auto flex w-full max-w-4xl justify-end px-3">
        <button
          onClick={() => scrollToBottom(true)}
          className="pointer-events-auto flex size-8 items-center justify-center rounded-full border border-(--color-border) bg-(--bg-card)/95 text-(--color-text-muted) shadow-md backdrop-blur transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
          aria-label="Back to latest message"
          title="Back to latest message"
        >
          <ChevronDown size={16} />
        </button>
      </div>
    )}

    {onAddSelectionToChat && onRequestSelectionDetails && onSendToSideChat && (
      <TextSelectionAction
        containerRef={scrollRef}
        onAddToChat={onAddSelectionToChat}
        onMoreDetails={onRequestSelectionDetails}
        onSendToSideChat={onSendToSideChat}
        enabled={!isEmpty}
      />
    )}
    </div>
  )
}
