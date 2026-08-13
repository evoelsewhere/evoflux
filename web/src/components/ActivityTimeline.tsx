/**
 * ActivityTimeline keeps one assistant turn's chronological work trace bounded.
 *
 * Thought remains a distinct thinking block between its surrounding tool
 * groups. Once answer prose starts, the timeline collapses so the result is
 * immediately visible in the parent transcript.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode, type TouchEvent, type UIEvent, type WheelEvent } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

import { BlockEnter } from './motion/BlockEnter'
import {
  groupConsecutiveToolCalls,
  ToolCallGroupCard,
  type ToolBlockGroup,
} from './ToolCallGroup'
import { ActivityStatus } from './motion/ActivityStatus'
import { cn } from '@/lib/utils'
import { isLatestStreamingItem } from '@/utils/turns'
import type { ContentBlock } from '@/api/types'

const BOTTOM_THRESHOLD = 48
const USER_SCROLL_DETACH_DELTA = 4

interface ActivityTimelineProps {
  blocks: ContentBlock[]
  /** True while the turn is live and final answer prose has not started. */
  isActive: boolean
  renderBlock: (args: { block: ContentBlock; isStreaming: boolean }) => ReactNode
  sessionId?: string
  latestMCPAppBlockIds?: Set<string>
  compact?: boolean
}

export function ActivityTimeline({
  blocks,
  ...props
}: ActivityTimelineProps) {
  if (blocks.length === 0) return null

  // A phase key gives each live/completed lifecycle the correct default:
  // open while work runs, collapsed once answer prose begins. Manual toggles
  // continue to work in either phase without synchronizing React state in an
  // effect.
  return (
    <ActivityTimelinePhase
      key={props.isActive ? 'active' : 'completed'}
      blocks={blocks}
      {...props}
    />
  )
}

function ActivityTimelinePhase({
  blocks,
  isActive,
  renderBlock,
  sessionId,
  latestMCPAppBlockIds,
  compact = false,
}: ActivityTimelineProps) {
  const [open, setOpen] = useState(isActive)
  const [showLatest, setShowLatest] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const pinnedRef = useRef(true)
  const lastScrollTopRef = useRef(0)
  const lastTouchYRef = useRef<number | null>(null)
  const renderItems = useMemo(() => groupConsecutiveToolCalls(blocks), [blocks])
  const actionCount = useMemo(
    () => blocks.reduce((count, block) => count + (block.type === 'tool' ? 1 : 0), 0),
    [blocks],
  )

  // Follow the newest Thought/tool only while the user has not scrolled up.
  useEffect(() => {
    const element = scrollRef.current
    if (!open || !isActive || !element || !pinnedRef.current) return
    element.scrollTop = element.scrollHeight
    lastScrollTopRef.current = element.scrollTop
  }, [blocks, isActive, open])

  const actionLabel = `${actionCount} ${actionCount === 1 ? 'action' : 'actions'}`
  const summaryLabel = `${isActive ? 'Working' : 'Worked'} · ${actionLabel}`

  const detach = () => {
    pinnedRef.current = false
    setShowLatest(true)
  }

  const handleScroll = (event: UIEvent<HTMLDivElement>) => {
    const element = event.currentTarget
    const nextScrollTop = element.scrollTop
    if (nextScrollTop < lastScrollTopRef.current - USER_SCROLL_DETACH_DELTA) detach()
    const isAtBottom = element.scrollHeight - nextScrollTop - element.clientHeight <= BOTTOM_THRESHOLD
    if (isAtBottom) {
      pinnedRef.current = true
      setShowLatest(false)
    }
    lastScrollTopRef.current = nextScrollTop
  }

  const handleWheel = (event: WheelEvent<HTMLDivElement>) => {
    if (event.deltaY < -USER_SCROLL_DETACH_DELTA) detach()
  }

  const handleTouchMove = (event: TouchEvent<HTMLDivElement>) => {
    const y = event.touches[0]?.clientY
    if (y == null) return
    if (lastTouchYRef.current !== null && y > lastTouchYRef.current + USER_SCROLL_DETACH_DELTA) {
      detach()
    }
    lastTouchYRef.current = y
  }

  const scrollToLatest = () => {
    const element = scrollRef.current
    if (!element) return
    pinnedRef.current = true
    setShowLatest(false)
    element.scrollTo({ top: element.scrollHeight, behavior: 'smooth' })
  }

  return (
    <section className="activity-timeline min-w-0" aria-label="Agent activity">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className={cn(
          'flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-xs',
          'text-(--color-text-muted) transition-colors hover:bg-(--bg-key)',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)',
        )}
        aria-expanded={open}
        aria-label={`${open ? 'Collapse' : 'Expand'} ${summaryLabel}`}
      >
        <ChevronRight
          size={12}
          className={cn('shrink-0 transition-transform', open && 'rotate-90')}
          aria-hidden="true"
        />
        {isActive ? (
          <ActivityStatus label="Working" className="text-xs" />
        ) : (
          <span className="font-medium text-(--color-text-2)">Worked</span>
        )}
        <span className="text-(--color-text-subtle)">· {actionLabel}</span>
      </button>

      {open && (
        <div className="relative min-w-0">
          <div
            ref={scrollRef}
            role="log"
            aria-label="Activity history"
            aria-live={isActive ? 'polite' : 'off'}
            className="activity-timeline-scroll space-y-2 px-1"
            onScroll={handleScroll}
            onWheel={handleWheel}
            onTouchMove={handleTouchMove}
            onTouchEnd={() => { lastTouchYRef.current = null }}
          >
            {renderItems.map((renderItem, index) => {
              const itemIsStreaming = isLatestStreamingItem(isActive, index, renderItems.length)
              if ('kind' in renderItem && (renderItem as ToolBlockGroup).kind === 'group') {
                return (
                  <BlockEnter key={(renderItem as ToolBlockGroup).id}>
                    <ToolCallGroupCard
                      group={renderItem as ToolBlockGroup}
                      isStreaming={itemIsStreaming}
                      sessionId={sessionId}
                      latestMCPAppBlockIds={latestMCPAppBlockIds}
                      compact={compact}
                    />
                  </BlockEnter>
                )
              }
              const block = renderItem as ContentBlock
              return (
                <BlockEnter key={block.id} disabled={itemIsStreaming && block.type === 'text'}>
                  {renderBlock({ block, isStreaming: itemIsStreaming })}
                </BlockEnter>
              )
            })}
          </div>

          {showLatest && isActive && (
            <button
              type="button"
              onClick={scrollToLatest}
              className="absolute right-2 bottom-2 inline-flex items-center gap-1 rounded-full border border-(--color-border) bg-(--bg-card)/95 px-2 py-1 text-[11px] text-(--color-text-2) shadow-sm backdrop-blur hover:bg-(--bg-key) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)"
              aria-label="Latest activity"
            >
              <ChevronDown size={11} aria-hidden="true" />
              Latest activity
            </button>
          )}
        </div>
      )}
    </section>
  )
}
