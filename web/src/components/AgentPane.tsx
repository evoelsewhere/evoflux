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
import { appendLiveTurnItems, getVisibleTurnWindow, partitionTurns } from '@/utils/turns'
import { latestDirectUserBlockId, mergeBlocks } from '@/utils/blocks'
import { latestMCPAppResourceBlockIds } from '@/utils/mcp-app-artifacts'
import { useTeamStore } from '@/stores/useTeamStore'
import { ContextBudgetBar } from '@/components/ContextBudgetBar'
import { useRegistryQuery } from '@/queries'
import { TierBadge } from './TierBadge'
import { resolveMemberTier } from '@/utils/tier'
import { usePinnedTranscript } from '@/hooks/usePinnedTranscript'
import type { AgentStream } from '@/stores/useTeamStore'
import { ActivityStatus } from './motion/ActivityStatus'
import { resolveAgentRole } from '@/lib/agent-roles'
import { TurnChangesCard } from './TurnChangesCard'
import type { ContentBlock, TodoItem } from '@/api/types'

// Split focuses on the current work. Mount a smaller initial history window
// so entering the layout does not parse dozens of old Markdown turns at once.
const INITIAL_RENDERED_TURNS = 32
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
  showTurnChanges?: boolean
}

function isDirectUserBlock(block: ContentBlock): boolean {
  return block.type === 'user' && !block.extra?.from_agent
}

export function AgentPane({
  name, stream, isLead, todos, isContinuing = false, onContinue,
  canMoveLeft, canMoveRight, onMoveLeft, onMoveRight,
  collapsible = true, showTurnChanges = false,
}: AgentPaneProps) {
  const [paneCollapsed, setPaneCollapsed] = useState(false)
  const [renderedTurnCount, setRenderedTurnCount] = useState(INITIAL_RENDERED_TURNS)
  const prevScrollHeightRef = useRef<number | null>(null)
  const pendingRestoreRef = useRef(false)
  const sessionId = useTeamStore((s) => s.sessionId) ?? undefined
  const sessionModel = useTeamStore((s) => s.sessionModel)
  const turnChanges = useTeamStore((s) => s.turnChanges)
  const registry = useRegistryQuery()
  const modelEntry = useMemo(() => {
    const modelId = sessionModel ?? stream.model
    if (!modelId || !registry.data) return undefined
    return registry.data.models.find((entry) => entry.id === modelId)
  }, [sessionModel, stream.model, registry.data])
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

  const allBlocks = useMemo(
    () => mergeBlocks(stream.blocks, stream.currentBlocks),
    [stream.blocks, stream.currentBlocks],
  )
  const latestUserBlockId = useMemo(() => latestDirectUserBlockId(allBlocks), [allBlocks])
  const finalizedTurnItems = useMemo(() => partitionTurns(stream.blocks), [stream.blocks])
  const turnItems = useMemo(
    () => appendLiveTurnItems(finalizedTurnItems, stream.currentBlocks, stream.blocks.length),
    [finalizedTurnItems, stream.blocks.length, stream.currentBlocks],
  )
  const { hiddenTurnCount, visibleTurnItems } = useMemo(
    () => getVisibleTurnWindow(turnItems, renderedTurnCount),
    [renderedTurnCount, turnItems],
  )
  const latestMCPAppBlockIds = useMemo(() => latestMCPAppResourceBlockIds(allBlocks), [allBlocks])
  const latestLiveUserBlockId = useMemo(
    () => latestDirectUserBlockId(stream.currentBlocks),
    [stream.currentBlocks],
  )
  const isEmpty = allBlocks.length === 0
  const {
    contentRef,
    restorePrependOffset,
    scrollRef,
    scrollToBottom,
    showScrollButton: showScrollBtn,
  } = usePinnedTranscript({
    isEmpty,
    contentKey: allBlocks.length,
    resetKey: sessionId,
    followKey: latestLiveUserBlockId ?? (isWorking && isContinuing ? `continue:${sessionId ?? ''}:${name}` : null),
  })

  const showEarlierTurns = useCallback(() => {
    const el = scrollRef.current
    if (el) {
      prevScrollHeightRef.current = el.scrollHeight
      pendingRestoreRef.current = true
    }
    setRenderedTurnCount((count) => Math.min(turnItems.length, count + TURN_RENDER_STEP))
  }, [scrollRef, turnItems.length])

  useEffect(() => {
    if (!pendingRestoreRef.current || prevScrollHeightRef.current === null) return
    pendingRestoreRef.current = false
    restorePrependOffset(prevScrollHeightRef.current)
    prevScrollHeightRef.current = null
  }, [renderedTurnCount, restorePrependOffset])

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
           <ContextBudgetBar
             compact
             used={stream.usage.promptTokens}
             max={modelEntry?.context_length ?? undefined}
             input={stream.usage.promptTokens}
             output={stream.usage.completionTokens}
             cached={stream.usage.cachedTokens}
             trigger={modelEntry?.summary_trigger_tokens}
           />
            <span aria-label={`Agent status: ${stream.status}`} className={`h-1.5 w-1.5 rounded-full ${
             isError ? 'bg-(--color-error)' : isWorking ? 'bg-(--color-accent)' : isOffline ? 'bg-(--color-text-subtle) opacity-50' : 'bg-(--color-success)'
           }`} />
         </div>
         {/* Pane controls: move + collapse */}
         <div className="flex shrink-0 items-center gap-0.5">
           {canMoveLeft && (
             <button
               type="button"
               onClick={onMoveLeft}
               className="flex h-7 w-7 items-center justify-center rounded-xs text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)"
               aria-label="Move pane left"
               title="Move left"
             >
               <ChevronLeft size={14} aria-hidden="true" />
             </button>
           )}
           {canMoveRight && (
             <button
               type="button"
               onClick={onMoveRight}
               className="flex h-7 w-7 items-center justify-center rounded-xs text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)"
               aria-label="Move pane right"
               title="Move right"
             >
               <ChevronRight size={14} aria-hidden="true" />
             </button>
           )}
           {collapsible && (
             <button
               type="button"
               onClick={() => setPaneCollapsed((c) => !c)}
               className="flex h-7 w-7 items-center justify-center rounded-xs text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)"
               aria-label={paneCollapsed ? 'Expand pane' : 'Collapse pane'}
               aria-expanded={!paneCollapsed}
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
      <div ref={scrollRef} className="flex-1 overflow-y-auto overscroll-contain" style={{ minHeight: 0 }}>
        {isEmpty && !isWorking && (isError || isOffline) && (
            <div className="flex h-full select-none flex-col items-center justify-center py-8">
              <p className="text-xs text-(--color-text-subtle)">{isError ? stream.lastError || 'Error' : 'Offline'}</p>
            </div>
          )}

         {allBlocks.length > 0 && (
            <div ref={contentRef} className="space-y-3 px-3 py-3">
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
                       <div key={item.block.id} className="oa-transcript-turn">
                         <BlockRenderer
                           block={item.block}
                           isStreaming={false}
                           compact
                           sessionId={sessionId}
                           onRevert={item.block.id === latestUserBlockId ? handleRevert : undefined}
                           latestMCPAppBlockIds={latestMCPAppBlockIds}
                           renderLeadingQuoteAsContext
                         />
                       </div>
                     )
                   }
                   // Me only the trailing turn (no user block after) can be "live"
                   const isTrailingTurn = hiddenTurnCount + k === turnItems.length - 1
                   return (
                     <div
                       key={`turn-${item.startIndex}-${item.blocks[0]?.id ?? k}`}
                       className={isTrailingTurn ? 'oa-latest-turn-runway' : 'oa-transcript-turn'}
                     >
                       <AssistantTurn
                         blocks={item.blocks}
                         startIndex={item.startIndex}
                         isWorking={isWorking}
                         isTrailingTurn={isTrailingTurn}
                         totalBlocks={allBlocks.length}
                         onContinue={onContinue}
                         sessionId={sessionId}
                         latestMCPAppBlockIds={latestMCPAppBlockIds}
                         renderBlock={({ block, isStreaming }) => (
                           <BlockRenderer
                             block={block}
                             isStreaming={isStreaming}
                             compact
                             sessionId={sessionId}
                             onRevert={isDirectUserBlock(block) && block.id === latestUserBlockId ? handleRevert : undefined}
                             latestMCPAppBlockIds={latestMCPAppBlockIds}
                             renderLeadingQuoteAsContext
                           />
                         )}
                       />
                       {showTurnChanges
                         && isLead
                         && !isWorking
                         && hiddenTurnCount + k === turnItems.length - 1
                         && turnChanges
                         && turnChanges.files.length > 0
                         && turnChanges.sessionId === sessionId && (
                         <TurnChangesCard changes={turnChanges} compact />
                       )}
                     </div>
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
          className="absolute right-2 bottom-2 z-(--z-panel) flex size-8 items-center justify-center rounded-full border border-(--color-border) bg-(--bg-card)/95 text-(--color-text-muted) shadow-md backdrop-blur transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
          aria-label="Back to latest message"
          title="Back to latest message"
        >
          <ChevronDown size={16} />
        </button>
      )}
      </div>
    </div>
  )
}
