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
import { getVisibleTurnWindow, partitionTurns, type TurnItem } from '@/utils/turns'
import { isDirectUserBlock, latestDirectUserBlockId } from '@/utils/blocks'
import { buildUserMessageNavigationItems } from '@/utils/user-message-navigation'
import { mcpAppResourceUri } from '@/utils/mcp-app-artifacts'
import { useTeamStore } from '@/stores/useTeamStore'
import { ActivityStatus } from './motion/ActivityStatus'
import { BlockEnter } from './motion/BlockEnter'
import { TextSelectionAction } from './TextSelectionAction'
import { TurnChangesCard } from './TurnChangesCard'
import { UserMessageNavigationRail } from './UserMessageNavigationRail'
import type { ContentBlock, TurnChangesPending } from '@/api/types'

const SCROLL_THRESHOLD = 40
const USER_SCROLL_DETACH_DELTA = 4
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
  const scrollRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const pinnedRef = useRef(true)
  const [showScrollBtn, setShowScrollBtn] = useState(false)
  const showScrollBtnRef = useRef(false)
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

  const showEarlierTurns = useCallback(() => {
    const el = scrollRef.current
    if (el) {
      prevScrollHeightRef.current = el.scrollHeight
      pendingRestoreRef.current = true
    }
    setRenderedTurnCount((count) => Math.min(turnItems.length, count + TURN_RENDER_STEP))
  }, [turnItems.length])

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

  const scrollToUserMessage = useCallback((
    messageId: string,
    behavior: ScrollBehavior,
  ) => {
    const container = scrollRef.current
    const item = userMessageNavigationItems.find((entry) => entry.id === messageId)
    if (!container || !item) return

    pinnedRef.current = false
    setScrollButtonVisible(true)

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
  }, [setScrollButtonVisible, turnItems.length, userMessageNavigationItems])

  // Me track scroll position and reveal/fetch older history near the top.
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    let lastScrollTop = el.scrollTop
    let scrollFrame: number | null = null
    let topLoadArmed = true
    const updatePinnedFromPosition = () => {
      scrollFrame = null
      const atBottom = isAtBottom()
      pinnedRef.current = atBottom
      setScrollButtonVisible(!atBottom)
    }
    const detachFromBottom = () => {
      pinnedRef.current = false
      setScrollButtonVisible(true)
    }
    const onScroll = () => {
      const nextScrollTop = el.scrollTop
      if (nextScrollTop < lastScrollTop - USER_SCROLL_DETACH_DELTA) {
        detachFromBottom()
      }
      lastScrollTop = nextScrollTop
      // Me: check + arm the load flag synchronously on the event, before any
      // rAF. Multiple scroll events can fire before a single rAF executes, so
      // if the guard lived inside rAF all queued callbacks would see the flag
      // as false and fire duplicate requests.
      if (el.scrollTop > LOAD_OLDER_THRESHOLD * 2) {
        topLoadArmed = true
      } else if (el.scrollTop <= LOAD_OLDER_THRESHOLD && topLoadArmed) {
        topLoadArmed = false
        if (hiddenTurnCount > 0) {
          showEarlierTurns()
        } else if (useTeamStore.getState().hasMore && !loadingOlderRef.current) {
          loadingOlderRef.current = true
          prevScrollHeightRef.current = el.scrollHeight
          pendingRestoreRef.current = true
          void useTeamStore.getState().loadOlderMessages().finally(() => {
            loadingOlderRef.current = false
          })
        }
      }

      if (scrollFrame === null) {
        scrollFrame = requestAnimationFrame(updatePinnedFromPosition)
      }
    }
    const onWheel = (e: WheelEvent) => {
      if (e.deltaY < -USER_SCROLL_DETACH_DELTA) detachFromBottom()
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    el.addEventListener('wheel', onWheel, { passive: true })
    return () => {
      if (scrollFrame !== null) cancelAnimationFrame(scrollFrame)
      el.removeEventListener('scroll', onScroll)
      el.removeEventListener('wheel', onWheel)
    }
  }, [hiddenTurnCount, isAtBottom, setScrollButtonVisible, showEarlierTurns])

  // Me restore scroll position after older messages are prepended.
  // We track a "pending restore" flag separately from blocks.length so
  // that SSE flushes (which also grow blocks) never accidentally trigger
  // a scroll-position restore.
  useEffect(() => {
    const el = scrollRef.current
    if (!el || !pendingRestoreRef.current || prevScrollHeightRef.current === null) return
    pendingRestoreRef.current = false
    el.scrollTop = el.scrollHeight - prevScrollHeightRef.current
    prevScrollHeightRef.current = null
  }, [blocks.length, renderedTurnCount])

  useEffect(() => {
    const pending = pendingUserNavigationRef.current
    const container = scrollRef.current
    if (!pending || !container) return
    const anchor = findUserMessageNavigationAnchor(container, pending.messageId)
    if (!anchor) return
    pendingUserNavigationRef.current = null
    anchor.scrollIntoView({ behavior: pending.behavior, block: 'start' })
  }, [blocks.length, renderedTurnCount, visibleTurnItems])

  // Follow the actual rendered transcript height instead of raw SSE chunks.
  // ResizeObserver is paint-coalesced, so the viewport moves on the same
  // cadence as the streaming Markdown reveal and no longer jitters ahead.
  useEffect(() => {
    const content = contentRef.current
    if (!content || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => {
      const el = scrollRef.current
      if (el && pinnedRef.current) el.scrollTop = el.scrollHeight
    })
    observer.observe(content)
    return () => observer.disconnect()
  }, [])

  // New blocks may mount without changing the wrapper's measured height
  // immediately; keep a synchronous fallback for that structural update.
  useEffect(() => {
    const el = scrollRef.current
    if (el && pinnedRef.current) el.scrollTop = el.scrollHeight
  }, [totalLen])

  const isEmpty = visibleCount === 0 && !isWorking
  useEffect(() => {
    if (!isEmpty) return
    pinnedRef.current = true
    if (scrollRef.current) scrollRef.current.scrollTop = 0
    const frame = requestAnimationFrame(() => setScrollButtonVisible(false))
    return () => cancelAnimationFrame(frame)
  }, [isEmpty, setScrollButtonVisible])

  return (
    <div className="@container/agent-view relative flex min-h-0 flex-1 flex-col">
    <div ref={scrollRef} className="flex-1 overflow-y-auto overscroll-contain">
      <div ref={contentRef} className="mx-auto max-w-4xl px-3 py-4">
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
                  // Map blockId → absolute index for streaming detection inside groups
                  const blockAbsIdx = new Map(item.blocks.map((b, j) => [b.id, item.startIndex + j]))
                 return (
                   <div
                     key={`turn-${item.startIndex}-${item.blocks[0]?.id ?? k}`}
                     className={turnIsStreaming ? undefined : 'oa-transcript-turn'}
                   >
                     <div className="space-y-2">
                       {groupedBlocks.map((renderItem, j) => {
                         if ('kind' in renderItem && (renderItem as ToolBlockGroup).kind === 'group') {
                           return (
                             <ToolCallGroupCard
                               key={`group-${item.startIndex}-${j}`}
                               group={renderItem as ToolBlockGroup}
                               isStreaming={turnIsStreaming}
                               sessionId={sessionId}
                               latestMCPAppBlockIds={latestMCPAppBlockIds}
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
              <div>
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
