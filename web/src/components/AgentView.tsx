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

import { memo, useState, useRef, useEffect, useLayoutEffect, useCallback, useMemo } from 'react'
import { ChatWelcome } from './ChatWelcome'
import { ChevronDown } from 'lucide-react'
import { BlockRenderer } from './BlockRenderer'
import { AssistantTurnFooter } from './AssistantTurnFooter'
import { AssistantTurnContent } from './AssistantTurnContent'
import { PendingMessageQueue } from './PendingMessageQueue'
import { appendLiveTurnItems, getVisibleTurnWindow, partitionTurns } from '@/utils/turns'
import { latestDirectUserBlockId } from '@/utils/blocks'
import { buildUserMessageNavigationItems } from '@/utils/user-message-navigation'
import { mcpAppResourceUri } from '@/utils/mcp-app-artifacts'
import { usePinnedTranscript } from '@/hooks/usePinnedTranscript'
import { cn } from '@/lib/utils'
import { useTeamStore } from '@/stores/useTeamStore'
import { activityLabelForPhase } from '@/lib/activity-phase'
import { ActivityStatus } from './motion/ActivityStatus'
import { TextSelectionAction } from './TextSelectionAction'
import { TurnChangesCard } from './TurnChangesCard'
import { UserMessageNavigationRail } from './UserMessageNavigationRail'
import { StreamingTurnHeader } from './StreamingTurnHeader'
import { TranscriptHistoryControl } from './TranscriptHistoryControl'
import { shouldShowPendingActivity } from '@/utils/transcript-layout'
import {
  HISTORY_INITIAL_RENDERED_TURNS,
  HISTORY_RENDER_STEP,
  historyLoadRearmThreshold,
  historyLoadThreshold,
  shouldPrimeOlderHistory,
} from '@/utils/transcript-history'
import type { ContentBlock, TurnChangesPending } from '@/api/types'

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

interface AssistantTranscriptTurnProps {
  blocks: ContentBlock[]
  canContinue?: () => void
  hasRunway: boolean
  latestMCPAppBlockIds: Set<string>
  sessionId?: string
  turnChanges: TurnChangesPending | null
  turnIsStreaming: boolean
}

interface UserTranscriptTurnProps {
  block: ContentBlock
  isNavigationAnchor: boolean
  isTopAnchor: boolean
  latestMCPAppBlockIds: Set<string>
  onRevert?: () => void
  sessionId?: string
}

/** Loaded user turns retain their subtree when an older window is prepended. */
const UserTranscriptTurn = memo(function UserTranscriptTurn({
  block,
  isNavigationAnchor,
  isTopAnchor,
  latestMCPAppBlockIds,
  onRevert,
  sessionId,
}: UserTranscriptTurnProps) {
  return (
    <div
      className="oa-transcript-turn"
      data-user-message-navigation-anchor={isNavigationAnchor ? block.id : undefined}
      data-transcript-top-anchor={isTopAnchor ? 'true' : undefined}
    >
      <BlockRenderer
        block={block}
        isStreaming={false}
        sessionId={sessionId}
        onRevert={onRevert}
        latestMCPAppBlockIds={latestMCPAppBlockIds}
        renderLeadingQuoteAsContext
      />
    </div>
  )
})

/** Historical turns keep stable block-array identities and skip live ticks. */
const AssistantTranscriptTurn = memo(function AssistantTranscriptTurn({
  blocks,
  canContinue,
  hasRunway,
  latestMCPAppBlockIds,
  sessionId,
  turnChanges,
  turnIsStreaming,
}: AssistantTranscriptTurnProps) {
  const turnStartedAt = useMemo(
    () => blocks.find((block) => block.startedAt)?.startedAt,
    [blocks],
  )

  return (
    <div className={hasRunway ? 'oa-latest-turn-runway' : 'oa-transcript-turn'}>
      {turnIsStreaming && <StreamingTurnHeader startedAt={turnStartedAt} />}
      <div className="space-y-2">
        <AssistantTurnContent
          blocks={blocks}
          turnIsStreaming={turnIsStreaming}
          sessionId={sessionId}
          latestMCPAppBlockIds={latestMCPAppBlockIds}
          renderBlock={({ block, isStreaming }) => (
            <BlockRenderer
              block={block}
              isStreaming={isStreaming}
              sessionId={sessionId}
              latestMCPAppBlockIds={latestMCPAppBlockIds}
            />
          )}
        />
        {!turnIsStreaming && (
          <AssistantTurnFooter
            turnBlocks={blocks}
            size="roomy"
            onContinue={canContinue}
          />
        )}
        {!turnIsStreaming && turnChanges && turnChanges.files.length > 0 && (
          <TurnChangesCard changes={turnChanges} />
        )}
      </div>
    </div>
  )
})

export function AgentView({ blocks, currentBlocks, isWorking, isError, lastError, isContinuing = false, onContinue, emptyState, onAddSelectionToChat, onRequestSelectionDetails, onSendToSideChat, turnChanges }: AgentViewProps) {
  const [renderedTurnCount, setRenderedTurnCount] = useState(HISTORY_INITIAL_RENDERED_TURNS)
  const sessionId = useTeamStore((s) => s.sessionId) ?? undefined
  const historyLoadStartBlockCountRef = useRef<number | null>(null)
  const pendingUserNavigationRef = useRef<{
    messageId: string
    behavior: ScrollBehavior
  } | null>(null)
  const topLoadArmedRef = useRef(true)
  const primedHistorySessionRef = useRef<string | null>(null)
  const loadingOlder = useTeamStore((state) => state._loadingOlder)
  const hasMoreHistory = useTeamStore((state) => state.hasMore)
  const nextHistoryCursor = useTeamStore((state) => state.nextCursor)

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
  const turnItems = useMemo(
    () => appendLiveTurnItems(finalizedTurnItems, currentBlocks, blocks.length),
    [blocks.length, currentBlocks, finalizedTurnItems],
  )
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
  // Which phase the working agent is in, so the runway can say whether
  // EvoFlux is still assembling the turn or the provider already has it.
  const activityPhase = useTeamStore((state) => {
    const streams = state.agentStreams ?? {}
    for (const stream of Object.values(streams)) {
      if (stream.status === 'working' && stream.phase) return stream.phase
    }
    return null
  })
  const showPendingActivity = shouldShowPendingActivity({
    currentBlocks,
    isContinuing,
    isError: Boolean(isError),
    isWorking,
  })

  // No before-state to capture: `overflow-anchor` on the scroller holds
  // the reader's position when turns are inserted above them.
  const loadOlderMessages = useCallback((element: HTMLDivElement | null) => {
    if (element) historyLoadStartBlockCountRef.current = blocks.length
    void useTeamStore.getState().loadOlderMessages()
  }, [blocks.length])

  const handleViewportScroll = useCallback((element: HTMLDivElement) => {
    const loadThreshold = historyLoadThreshold(element.clientHeight)
    if (element.scrollTop > historyLoadRearmThreshold(element.clientHeight)) {
      topLoadArmedRef.current = true
      return
    }
    if (element.scrollTop > loadThreshold || !topLoadArmedRef.current) return

    topLoadArmedRef.current = false
    if (hiddenTurnCount > 0) {
      setRenderedTurnCount((count) => Math.min(turnItems.length, count + HISTORY_RENDER_STEP))
      return
    }
    if (!useTeamStore.getState().hasMore || useTeamStore.getState()._loadingOlder) return
    loadOlderMessages(element)
  }, [hiddenTurnCount, loadOlderMessages, turnItems.length])

  const isEmpty = visibleCount === 0 && !isWorking
  const {
    contentRef,
    detach: detachFromBottom,
    sentinelRef,
    scrollRef,
    scrollToBottom,
    showScrollButton: showScrollBtn,
  } = usePinnedTranscript({
    isEmpty,
    contentKey: totalLen,
    resetKey: sessionId,
    followKey: isWorking && isContinuing ? `continue:${sessionId ?? ''}` : null,
    // On reload the newest prompt is already finalized. Keep using the same
    // direct-user id as a live turn moves into history so the viewport anchors
    // once without jumping again when the response completes.
    topAnchorKey: latestUserBlockId,
    onScrollFrame: handleViewportScroll,
  })

  // Prime one older server page when the initial transcript is shorter than
  // the upward buffer. This moves network latency off the user's first fast
  // scroll while preserving the same anchor-based prepend behavior.
  useEffect(() => {
    if (!sessionId || isEmpty || primedHistorySessionRef.current === sessionId) return
    const frame = requestAnimationFrame(() => {
      const element = scrollRef.current
      if (!element || primedHistorySessionRef.current === sessionId) return
      if (loadingOlder) return
      primedHistorySessionRef.current = sessionId
      if (!shouldPrimeOlderHistory({
        canLoadOlder: hasMoreHistory && Boolean(nextHistoryCursor),
        clientHeight: element.clientHeight,
        scrollHeight: element.scrollHeight,
      })) return
      loadOlderMessages(element)
    })
    return () => cancelAnimationFrame(frame)
  }, [
    hasMoreHistory,
    isEmpty,
    loadOlderMessages,
    loadingOlder,
    nextHistoryCursor,
    scrollRef,
    sessionId,
  ])

  const showEarlierTurns = useCallback(() => {
    setRenderedTurnCount((count) => Math.min(turnItems.length, count + HISTORY_RENDER_STEP))
  }, [turnItems.length])

  const loadOlderFromControl = useCallback(() => {
    loadOlderMessages(scrollRef.current)
  }, [loadOlderMessages, scrollRef])

  useLayoutEffect(() => {
    topLoadArmedRef.current = true
    primedHistorySessionRef.current = null
    historyLoadStartBlockCountRef.current = null
    pendingUserNavigationRef.current = null
  }, [sessionId])

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

  useEffect(() => {
    const startCount = historyLoadStartBlockCountRef.current
    if (loadingOlder || startCount === null) return
    historyLoadStartBlockCountRef.current = null
    if (blocks.length !== startCount) return
  }, [blocks.length, loadingOlder])

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
    {/* `overflow-anchor:auto` is load-bearing: the browser keeps the
        reader's position when older turns mount above the viewport, which
        used to be done by hand from captured scroll offsets. */}
    <div ref={scrollRef} className="flex flex-1 flex-col overflow-y-auto overscroll-contain [overflow-anchor:auto]">
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
              <TranscriptHistoryControl
                hiddenTurnCount={hiddenTurnCount}
                revealStep={HISTORY_RENDER_STEP}
                onRevealLoaded={showEarlierTurns}
                onLoadOlder={loadOlderFromControl}
              />
              {visibleTurnItems.map((item, k) => {
                 const globalTurnIndex = hiddenTurnCount + k
                 if (item.kind === 'user') {
                   const navigationItem = userMessageNavigationIds.has(item.block.id)
                   return (
                     <UserTranscriptTurn
                       key={item.block.id}
                       block={item.block}
                       isNavigationAnchor={navigationItem}
                       isTopAnchor={item.block.id === latestUserBlockId}
                       sessionId={sessionId}
                       onRevert={item.block.id === latestUserBlockId ? handleRevert : undefined}
                       latestMCPAppBlockIds={latestMCPAppBlockIds}
                     />
                   )
                 }
                  // Only the trailing turn (no user block after) can be "live".
                  const isTrailingTurn = globalTurnIndex === turnItems.length - 1
                  const turnIsStreaming = isWorking && isTrailingTurn
                 return (
                   <AssistantTranscriptTurn
                     key={`turn-${item.startIndex}-${item.blocks[0]?.id ?? k}`}
                     blocks={item.blocks}
                     turnIsStreaming={turnIsStreaming}
                     hasRunway={isTrailingTurn && !showPendingActivity}
                     canContinue={isTrailingTurn && !isWorking ? onContinue : undefined}
                     sessionId={sessionId}
                     latestMCPAppBlockIds={latestMCPAppBlockIds}
                     turnChanges={
                       !isWorking
                         && isTrailingTurn
                         && turnChanges
                         && turnChanges.sessionId === sessionId
                         ? turnChanges
                         : null
                     }
                   />
                 )
                })}

            {/* Keep one stable activity state across the POST → first SSE gap.
             * Only a direct user message may reserve this pending runway;
             * internal system/wait messages are deliberately excluded.
             */}
            {showPendingActivity && (
              <div className="oa-active-turn-runway">
                <ActivityStatus
                  label={activityLabelForPhase(activityPhase)}
                  className="py-1 pl-0.5 text-xs"
                />
              </div>
            )}

            <PendingMessageQueue />

            {isError && lastError && (
             <div className="mt-3 rounded-lg border border-(--color-error) bg-(--color-error-subtle) px-3 py-2">
               <p className="text-xs text-(--color-error)">{lastError}</p>
             </div>
           )}

         </div>
        {/* Whether this is visible is how the viewport knows it is at the
            bottom, so nothing has to measure the scroller. Excluded from
            scroll anchoring: as the last child it would otherwise be the
            browser's preferred anchor and hold the view at the end. */}
        <div
          ref={sentinelRef}
          aria-hidden="true"
          className="h-px w-full shrink-0 [overflow-anchor:none]"
        />
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
