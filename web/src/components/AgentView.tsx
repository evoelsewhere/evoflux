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
import EvoFluxLogo from '@/assets/brand/evoflux-app-icon.png'
import { ChatWelcome } from './ChatWelcome'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { AgentChip } from './ui/agent-chip'
import { BlockRenderer } from './BlockRenderer'
import { AssistantTurnFooter } from './AssistantTurnFooter'
import { groupConsecutiveToolCalls, ToolCallGroupCard } from './ToolCallGroup'
import type { ToolBlockGroup } from './ToolCallGroup'
import { PendingMessageQueue } from './PendingMessageQueue'
import { getVisibleTurnWindow, partitionTurns, type TurnItem } from '@/utils/turns'
import { isDirectUserBlock, latestDirectUserBlockId } from '@/utils/blocks'
import { mcpAppResourceUri } from '@/utils/mcp-app-artifacts'
import { resolveAgentRole } from '@/lib/agent-roles'
import { useTeamStore } from '@/stores/useTeamStore'
import { LoadingVerb } from './motion/LoadingVerb'
import { SessionChapterRail } from './SessionChapterRail'
import { TextSelectionAction } from './TextSelectionAction'
import type { Chapter, ContentBlock } from '@/api/types'

const SCROLL_THRESHOLD = 40
const USER_SCROLL_DETACH_DELTA = 4
const LOAD_OLDER_THRESHOLD = 300
const INITIAL_RENDERED_TURNS = 80
const TURN_RENDER_STEP = 80

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
  /** Session chapters for anchor markers and TOC dividers. */
  chapters?: Chapter[]
  /** Quote selected transcript text into the primary composer. */
  onAddSelectionToChat?: (selectedText: string) => void
  /** Prepare a primary-chat prompt requesting more detail about selected text. */
  onRequestSelectionDetails?: (selectedText: string) => void
  /** Open a side-chat thread grounded in selected transcript text. */
  onSendToSideChat?: (selectedText: string) => void
}

export function AgentView({ blocks, currentBlocks, isWorking, isError, lastError, isContinuing = false, onContinue, emptyState, chapters, onAddSelectionToChat, onRequestSelectionDetails, onSendToSideChat }: AgentViewProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const pinnedRef = useRef(true)
  const [showScrollBtn, setShowScrollBtn] = useState(false)
  const [renderedTurnCount, setRenderedTurnCount] = useState(INITIAL_RENDERED_TURNS)
  const sessionId = useTeamStore((s) => s.sessionId) ?? undefined
  const activeAgent = useTeamStore((s) => s.activeAgent)
  const prevScrollHeightRef = useRef<number | null>(null)
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

  const finalizedMCPAppIdsByUri = useMemo(() => {
    const byUri = new Map<string, string>()
    for (const block of blocks) {
      if (block.type !== 'tool' || !block.toolDone) continue
      const uri = mcpAppResourceUri(block)
      if (uri) byUri.set(uri, block.id)
    }
    return byUri
  }, [blocks])
  const mcpAppIdsRef = useRef<Set<string>>(new Set())
  const latestMCPAppBlockIds = useMemo(() => {
    let byUri = finalizedMCPAppIdsByUri
    if (currentBlocks.length > 0) {
      byUri = new Map(finalizedMCPAppIdsByUri)
      for (const block of currentBlocks) {
        if (block.type !== 'tool' || !block.toolDone) continue
        const uri = mcpAppResourceUri(block)
        if (uri) byUri.set(uri, block.id)
      }
    }
    const next = new Set(byUri.values())
    // Keep the previous Set identity when contents are unchanged so the
    // memoized BlockRenderer isn't invalidated on every streamed chunk.
    const prev = mcpAppIdsRef.current
    if (prev.size === next.size) {
      let same = true
      for (const id of next) {
        if (!prev.has(id)) { same = false; break }
      }
      if (same) return prev
    }
    mcpAppIdsRef.current = next
    return next
  }, [currentBlocks, finalizedMCPAppIdsByUri])

  const chapterByMessageId = useMemo(() => {
    const map = new Map<string, Chapter>()
    for (const ch of chapters ?? []) {
      if (ch.message_id) map.set(ch.message_id, ch)
    }
    return map
  }, [chapters])

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

  // Me track scroll position and reveal/fetch older history near the top.
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    let lastScrollTop = el.scrollTop
    const updatePinnedFromPosition = () => {
      const atBottom = isAtBottom()
      pinnedRef.current = atBottom
      // Me: only flip state when the boolean actually changes. Calling
      // setState with the current value on every scroll tick still
      // schedules a re-render, which cascades through MarkdownBlock /
      // ReactMarkdown and was enough to re-mount inline ``<video>``
      // elements mid-playback (flicker).
      setShowScrollBtn((prev) => (prev === !atBottom ? prev : !atBottom))
    }
    const detachFromBottom = () => {
      pinnedRef.current = false
      setShowScrollBtn(true)
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
      if (el.scrollTop <= LOAD_OLDER_THRESHOLD) {
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

      requestAnimationFrame(updatePinnedFromPosition)
    }
    const onWheel = (e: WheelEvent) => {
      if (e.deltaY < -USER_SCROLL_DETACH_DELTA) detachFromBottom()
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    el.addEventListener('wheel', onWheel, { passive: true })
    return () => {
      el.removeEventListener('scroll', onScroll)
      el.removeEventListener('wheel', onWheel)
    }
  }, [hiddenTurnCount, isAtBottom, showEarlierTurns])

  // Me restore scroll position after older messages are prepended.
  // We track a "pending restore" flag separately from blocks.length so
  // that SSE flushes (which also grow blocks) never accidentally trigger
  // a scroll-position restore.
  const pendingRestoreRef = useRef(false)
  useEffect(() => {
    const el = scrollRef.current
    if (!el || !pendingRestoreRef.current || prevScrollHeightRef.current === null) return
    pendingRestoreRef.current = false
    el.scrollTop = el.scrollHeight - prevScrollHeightRef.current
    prevScrollHeightRef.current = null
  }, [blocks.length, renderedTurnCount])

  // Me single scroll effect — block count or last block text changed
  const lastContent =
    currentBlocks[currentBlocks.length - 1]?.content ??
    blocks[blocks.length - 1]?.content ??
    ''
  useEffect(() => {
    if (pinnedRef.current) scrollToBottom()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [totalLen, lastContent])

  const isEmpty = visibleCount === 0 && !isWorking
  const agentLabel = activeAgent ?? 'evoflux'

  useEffect(() => {
    if (!isEmpty) return
    pinnedRef.current = true
    setShowScrollBtn(false)
    if (scrollRef.current) scrollRef.current.scrollTop = 0
  }, [isEmpty])

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
    <div ref={scrollRef} className="flex-1 overflow-y-auto">
      <div className={`mx-auto max-w-3xl px-4 py-6 ${chapterByMessageId.size > 0 ? 'lg:pl-16' : ''}`}>
        {isEmpty && (
           emptyState ?? <ChatWelcome />
         )}

         <div className="space-y-6">
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
                   const chapter = chapterByMessageId.get(item.block.id)
                   return (
                     <div key={item.block.id} data-chapter-anchor={item.block.id}>
                       {chapter && (
                         <div className="mb-3 flex items-center gap-2 text-xs text-(--color-text-muted)">
                           <div className="h-px flex-1 bg-(--color-border)" />
                           <span className="font-medium">{chapter.title}</span>
                           <div className="h-px flex-1 bg-(--color-border)" />
                         </div>
                       )}
                       <BlockRenderer
                         block={item.block}
                         isStreaming={false}
                         sessionId={sessionId}
                         onRevert={item.block.id === latestUserBlockId ? handleRevert : undefined}
                         latestMCPAppBlockIds={latestMCPAppBlockIds}
                       />
                     </div>
                   )
                 }
                 // Me only the trailing turn (no user block after) can be "live"
                  const isTrailingTurn = globalTurnIndex === turnItems.length - 1
                  const turnIsStreaming = isWorking && isTrailingTurn
                  const canContinue = isTrailingTurn && !isWorking ? onContinue : undefined
                  // Don't collapse the live streaming turn — keep per-tool cards
                  // visible so long runs show real-time activity instead of a
                  // static "Read N files" row while the agent is still working.
                  const groupedBlocks = turnIsStreaming
                    ? item.blocks
                    : groupConsecutiveToolCalls(item.blocks)
                  // Map blockId → absolute index for streaming detection inside groups
                  const blockAbsIdx = new Map(item.blocks.map((b, j) => [b.id, item.startIndex + j]))
                 return (
                   <div key={`turn-${item.startIndex}-${item.blocks[0]?.id ?? k}`}>
                     <div className="mb-2 flex items-center gap-1.5">
                       <img src={EvoFluxLogo} width={12} height={12} className="shrink-0 rounded-xs opacity-70" alt="" aria-hidden="true" />
                       <AgentChip
                         role={resolveAgentRole(agentLabel)}
                         label={agentLabel}
                         active={turnIsStreaming}
                         className="min-w-0 truncate px-2 py-0.5 text-[11px]"
                         dotClassName={turnIsStreaming ? 'animate-pulse bg-(--color-accent)' : undefined}
                       />
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
                           <div key={block.id} className="block-reveal">
                             <BlockRenderer
                               block={block}
                               isStreaming={isStreaming}
                               sessionId={sessionId}
                               onRevert={isDirectUserBlock(block) && block.id === latestUserBlockId ? handleRevert : undefined}
                               latestMCPAppBlockIds={latestMCPAppBlockIds}
                             />
                           </div>
                         )
                       })}
                       {!turnIsStreaming && (
                         <AssistantTurnFooter
                           turnBlocks={item.blocks}
                           size="roomy"
                           onContinue={canContinue}
                         />
                       )}
                     </div>
                   </div>
                 )
                })}

            {/* Me show loading verb when:
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
                <div className="mb-2 flex items-center gap-1.5">
                  <img src={EvoFluxLogo} width={12} height={12} className="shrink-0 rounded-xs opacity-70" alt="" aria-hidden="true" />
                  <AgentChip
                    role={resolveAgentRole(agentLabel)}
                    label={agentLabel}
                    active
                    className="min-w-0 truncate px-2 py-0.5 text-[11px]"
                    dotClassName="animate-pulse bg-(--color-accent)"
                  />
                </div>
                <LoadingVerb className="py-1 pl-0.5" />
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
    <SessionChapterRail
      chapters={chapters ?? []}
      containerRef={scrollRef}
      sessionId={sessionId}
    />
    {showScrollBtn && !isEmpty && (
        <button
          onClick={() => scrollToBottom(true)}
          className="absolute bottom-16 left-1/2 z-(--z-panel) -translate-x-1/2 rounded-full border border-(--color-border) bg-(--bg-card) p-1 text-(--color-text-muted) transition-colors hover:text-(--color-text-2)"
          aria-label="Scroll to bottom"
        >
          <ChevronDown size={16} />
        </button>

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
