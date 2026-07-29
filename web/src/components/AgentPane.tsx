/**
 * AgentPane — compact single-agent pane used by the split view.
 *
 * Renders the same ContentBlock[] stream as `AgentView` via the shared
 * `BlockRenderer` (handoffs, webbridge, quote context included) in a denser
 * layout with a small header for tiling alongside other panes.
 *
 * Blocks are grouped into turns via `partitionTurns`. Each finalized turn
 * renders through `AssistantTurn` (tool groups + footer); the trailing turn
 * hides its footer while the agent is actively streaming.
 */
import { useState, useRef, useEffect, useCallback, useMemo } from 'react'

import { ChevronDown, ChevronUp, ChevronLeft, ChevronRight } from 'lucide-react'
import { AssistantTurn } from './AssistantTurnFooter'
import { BlockRenderer } from './BlockRenderer'
import { AgentChip } from './ui/agent-chip'
import { getVisibleTurnWindow, partitionTurns } from '@/utils/turns'
import { latestDirectUserBlockId, mergeBlocks } from '@/utils/blocks'
import { formatTokens } from '@/utils/format'
import { latestMCPAppResourceBlockIds } from '@/utils/mcp-app-artifacts'
import { useTeamStore } from '@/stores/useTeamStore'
import { TierBadge } from './TierBadge'
import { resolveMemberTier } from '@/utils/tier'
import type { AgentStream } from '@/stores/useTeamStore'
import { ActivityStatus } from './motion/ActivityStatus'
import { resolveAgentRole } from '@/lib/agent-roles'
import type { ContentBlock, TodoItem } from '@/api/types'

const SCROLL_THRESHOLD = 40
const USER_SCROLL_DETACH_DELTA = 4
const INITIAL_RENDERED_TURNS = 80
const TURN_RENDER_STEP = 80

interface AgentPaneProps {
  name: string
  stream: AgentStream
  isLead: boolean
  todos?: TodoItem[]
  isContinuing?: boolean
  onContinue?: () => void
  canMoveLeft?: boolean
  canMoveRight?: boolean
  onMoveLeft?: () => void
  onMoveRight?: () => void
  collapsible?: boolean
}

function isDirectUserBlock(block: ContentBlock): boolean {
  return block.type === 'user' && !block.extra?.from_agent
}

export function AgentPane({
  name, stream, isLead, todos, isContinuing = false, onContinue,
  canMoveLeft, canMoveRight, onMoveLeft, onMoveRight,
  collapsible = true,
}: AgentPaneProps) {
  const [paneCollapsed, setPaneCollapsed] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [renderedTurnCount, setRenderedTurnCount] = useState(INITIAL_RENDERED_TURNS)
  const prevScrollHeightRef = useRef<number | null>(null)
  const pendingRestoreRef = useRef(false)
  const sessionId = useTeamStore((s) => s.sessionId) ?? undefined
  const handleRevert = useCallback(() => {
    void useTeamStore.getState().undoTeam()
  }, [])
  const isWorking = stream.status === 'working'
  const isError   = stream.status === 'error'
  const isOffline = stream.status === 'offline'
  // Me show waiting indicator when a user message exists but the agent hasn't woken yet
  const isPending = !isWorking && !isError && !isOffline && stream.currentBlocks.some(isDirectUserBlock)

  const memberTier = useMemo(
    () => (!isLead && todos ? resolveMemberTier(todos, name) : null),
    [isLead, todos, name],
  )

  const pinnedRef = useRef(true)
  const [showScrollBtn, setShowScrollBtn] = useState(false)

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

  // Me detect user scroll intent before stream updates can snap the pane back
  // to the bottom. Scroll catches scrollbar/keyboard movement; wheel/touchmove
  // detach immediately when the user starts moving upward.
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    let lastScrollTop = el.scrollTop
    let lastTouchY: number | null = null
    const updatePinnedFromPosition = () => {
      const atBottom = isAtBottom()
      pinnedRef.current = atBottom
      // Me: only flip state when the boolean actually changes. Calling
      // setState with the current value on every wheel tick still
      // schedules a re-render, which can cascade through MarkdownBlock /
      // ReactMarkdown and re-mount inline media elements mid-playback.
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
      requestAnimationFrame(updatePinnedFromPosition)
    }
    const onWheel = (e: WheelEvent) => {
      if (e.deltaY < -USER_SCROLL_DETACH_DELTA) detachFromBottom()
    }
    const onTouchMove = (e: TouchEvent) => {
      const y = e.touches[0]?.clientY
      if (y == null) return
      if (lastTouchY !== null && y > lastTouchY + USER_SCROLL_DETACH_DELTA) detachFromBottom()
      lastTouchY = y
    }
    const onTouchEnd = () => {
      lastTouchY = null
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    el.addEventListener('wheel', onWheel, { passive: true })
    el.addEventListener('touchmove', onTouchMove, { passive: true })
    el.addEventListener('touchend', onTouchEnd, { passive: true })
    el.addEventListener('touchcancel', onTouchEnd, { passive: true })
    return () => {
      el.removeEventListener('scroll', onScroll)
      el.removeEventListener('wheel', onWheel)
      el.removeEventListener('touchmove', onTouchMove)
      el.removeEventListener('touchend', onTouchEnd)
      el.removeEventListener('touchcancel', onTouchEnd)
    }
  }, [isAtBottom])

  const allBlocks = useMemo(
    () => mergeBlocks(stream.blocks, stream.currentBlocks),
    [stream.blocks, stream.currentBlocks],
  )
  const latestUserBlockId = useMemo(() => latestDirectUserBlockId(allBlocks), [allBlocks])
  const turnItems = useMemo(() => partitionTurns(allBlocks), [allBlocks])
  const { hiddenTurnCount, visibleTurnItems } = useMemo(
    () => getVisibleTurnWindow(turnItems, renderedTurnCount),
    [renderedTurnCount, turnItems],
  )
  const latestMCPAppBlockIds = useMemo(() => latestMCPAppResourceBlockIds(allBlocks), [allBlocks])

  const showEarlierTurns = useCallback(() => {
    const el = scrollRef.current
    if (el) {
      prevScrollHeightRef.current = el.scrollHeight
      pendingRestoreRef.current = true
    }
    setRenderedTurnCount((count) => Math.min(turnItems.length, count + TURN_RENDER_STEP))
  }, [turnItems.length])

  useEffect(() => {
    const el = scrollRef.current
    if (!el || !pendingRestoreRef.current || prevScrollHeightRef.current === null) return
    pendingRestoreRef.current = false
    el.scrollTop = el.scrollHeight - prevScrollHeightRef.current
    prevScrollHeightRef.current = null
  }, [renderedTurnCount])

  // Me single scroll effect — block count or last block text changed
  const lastBlockContent = allBlocks[allBlocks.length - 1]?.content ?? ''
  useEffect(() => {
    if (pinnedRef.current) scrollToBottom()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allBlocks.length, lastBlockContent])

  const isEmpty = allBlocks.length === 0

  useEffect(() => {
    if (!isEmpty) return
    pinnedRef.current = true
    setShowScrollBtn(false)
    if (scrollRef.current) scrollRef.current.scrollTop = 0
  }, [isEmpty])

  const paneClass = isError
    ? 'ring-1 ring-inset ring-(--color-error)/40 shadow-sm'
    : isWorking
    ? 'ring-1 ring-inset ring-(--color-border-strong) shadow-[0_4px_16px_rgba(0,0,0,.3),0_1px_3px_rgba(0,0,0,.2)]'
    : isLead
    ? 'ring-1 ring-inset ring-(--color-border-strong) shadow-md'
    : 'ring-1 ring-inset ring-(--color-border-subtle) shadow-sm'

  return (
    <div
      className={`flex h-full flex-col overflow-hidden rounded-lg bg-(--bg-card) transition-[box-shadow,border-color,opacity] duration-(--motion-base) ${paneClass}`}
    >
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-(--color-border-subtle) bg-(--bg-key)/50 px-3 py-2.5">
         <div className="flex min-w-0 flex-1 items-center gap-1.5">
           <AgentChip
             role={resolveAgentRole(name)}
             label={name}
             active={isLead || isWorking}
             className="min-w-0 truncate px-2 py-1"
             dotClassName={
               isError
                 ? 'bg-(--color-error)'
                 : isWorking
                   ? 'animate-pulse bg-(--color-accent)'
                   : isOffline
                     ? 'bg-(--color-text-subtle) opacity-50'
                     : undefined
             }
           />
           {isLead && (
             <span className="shrink-0 rounded-sm bg-(--bg-key) px-1 py-0.5 text-xs text-(--color-accent)">
               lead
             </span>
           )}
           {memberTier && <TierBadge tier={memberTier} />}
         </div>
         <div className="flex items-center gap-1 text-xs text-(--color-text-subtle)">
           {stream.usage.totalTokens > 0 && (
             <span
                className="flex h-8 min-w-8 items-center justify-center rounded-full bg-(--bg-key) px-2 font-mono text-xs text-(--color-text)"
               title={`Input: ${stream.usage.promptTokens.toLocaleString()} · Output: ${stream.usage.completionTokens.toLocaleString()} · Cache: ${stream.usage.cachedTokens.toLocaleString()}`}
             >
               {formatTokens(stream.usage.promptTokens)}
             </span>
           )}
            <span aria-label={`Agent status: ${stream.status}`} className={`h-1.5 w-1.5 rounded-full ${
             isError ? 'bg-(--color-error)' : isWorking ? 'bg-(--color-accent)' : isOffline ? 'bg-(--color-text-subtle) opacity-50' : 'bg-(--color-success)'
           }`} />
         </div>
         {/* Pane controls: move + collapse */}
         <div className="flex shrink-0 items-center gap-0.5">
           {canMoveLeft && (
             <button
               onClick={onMoveLeft}
               className="flex h-7 w-7 items-center justify-center rounded-xs text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
               title="Move left"
             >
               <ChevronLeft size={14} aria-hidden="true" />
             </button>
           )}
           {canMoveRight && (
             <button
               onClick={onMoveRight}
               className="flex h-7 w-7 items-center justify-center rounded-xs text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
               title="Move right"
             >
               <ChevronRight size={14} aria-hidden="true" />
             </button>
           )}
           {collapsible && (
             <button
               onClick={() => setPaneCollapsed((c) => !c)}
               className="flex h-7 w-7 items-center justify-center rounded-xs text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
               title={paneCollapsed ? 'Expand' : 'Collapse'}
             >
               {paneCollapsed
                 ? <ChevronDown size={14} aria-hidden="true" />
                 : <ChevronUp size={14} aria-hidden="true" />}
             </button>
           )}
         </div>
       </div>

      {/* Body */}
      <div className={collapsible && paneCollapsed ? 'hidden' : 'relative flex min-h-0 flex-1 flex-col'}>
      <div ref={scrollRef} className="flex-1 overflow-y-auto" style={{ minHeight: 0 }}>
        {isEmpty && !isWorking && (isError || isOffline) && (
            <div className="flex h-full select-none flex-col items-center justify-center py-8">
              <p className="text-xs text-(--color-text-subtle)">{isError ? stream.lastError || 'Error' : 'Offline'}</p>
            </div>
          )}

         {allBlocks.length > 0 && (
            <div className="space-y-3 px-3 py-3">
               {hiddenTurnCount > 0 && (
                 <div className="flex justify-center pb-1">
                   <button
                     type="button"
                     onClick={showEarlierTurns}
                     className="inline-flex min-h-8 items-center gap-1 rounded-full border border-(--color-border) bg-(--bg-card) px-2.5 py-1 text-xs text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:ring-2 focus-visible:ring-(--focus-ring) focus-visible:outline-none"
                     aria-label={`Show ${Math.min(TURN_RENDER_STEP, hiddenTurnCount)} earlier turns`}
                   >
                     <ChevronUp size={12} aria-hidden="true" />
                     {hiddenTurnCount} earlier
                   </button>
                 </div>
               )}
               {visibleTurnItems.map((item, k) => {
                   if (item.kind === 'user') {
                     return (
                       <BlockRenderer
                         key={item.block.id}
                         block={item.block}
                         isStreaming={false}
                         compact
                         sessionId={sessionId}
                         onRevert={item.block.id === latestUserBlockId ? handleRevert : undefined}
                         latestMCPAppBlockIds={latestMCPAppBlockIds}
                       />
                     )
                   }
                   // Me only the trailing turn (no user block after) can be "live"
                    const isTrailingTurn = hiddenTurnCount + k === turnItems.length - 1
                   return (
                     <AssistantTurn
                       key={`turn-${item.startIndex}-${item.blocks[0]?.id ?? k}`}
                       blocks={item.blocks}
                       startIndex={item.startIndex}
                       finalizedCount={stream.blocks.length}
                       isWorking={isWorking}
                       isTrailingTurn={isTrailingTurn}
                       totalBlocks={allBlocks.length}
                       onContinue={onContinue}
                       renderBlock={({ block, isStreaming }) => (
                         <BlockRenderer
                           block={block}
                           isStreaming={isStreaming}
                           compact
                           sessionId={sessionId}
                           latestMCPAppBlockIds={latestMCPAppBlockIds}
                         />
                       )}
                     />
                   )
                  })}
              </div>
            )}

          {/* Show a stable activity state while waiting for the first agent block.
            * `[].every()` returns true, so the working branch also requires a non-empty
            * currentBlocks list — otherwise the indicator persists after `done` flushes
            * the buffer if a stale `working` status briefly survives. */}
          {(isPending ||
            (isWorking && (
              (isContinuing && stream.currentBlocks.length === 0) ||
              (stream.currentBlocks.length > 0 && stream.currentBlocks.every((b) => b.type === 'user'))
            ))) && (
            <div className="flex items-center gap-2 px-3 pt-3" role="status" aria-label={`${name} is preparing a response`}>
              <ActivityStatus className="text-xs" />
            </div>
          )}

          {isError && stream.lastError && (
           <div className="mx-3 mt-3 rounded-lg border border-(--color-error) bg-(--color-error-subtle) px-3 py-2">
             <p className="text-xs text-(--color-error)">{stream.lastError}</p>
           </div>
          )}
      </div>
      {showScrollBtn && (
        <button
          onClick={() => scrollToBottom(true)}
          className="absolute bottom-2 left-1/2 z-(--z-panel) -translate-x-1/2 rounded-full border border-(--color-border) bg-(--bg-card) p-1 text-(--color-text-muted) transition-colors hover:text-(--color-text-2)"
          aria-label="Scroll to bottom"
        >
          <ChevronDown size={16} />
        </button>
      )}
      </div>
    </div>
  )
}
