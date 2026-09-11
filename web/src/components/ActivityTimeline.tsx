/**
 * One stable, bounded activity group for an adjacent run of semantic
 * thinking/tool events. Content events split groups before they reach here.
 */
import { useMemo, useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

import { BlockEnter } from './motion/BlockEnter'
import { groupLabel } from './ToolCallGroup'
import { EasdToolReviewAction } from './easd/EasdToolReviewAction'
import { easdToolReviewTarget } from './easd/easdToolReviewTarget'
import { usePinnedTranscript } from '@/hooks/usePinnedTranscript'
import { cn } from '@/lib/utils'
import type { ContentBlock } from '@/api/types'

interface ActivityTimelineProps {
  blocks: ContentBlock[]
  /** True only when this is the trailing segment of a live turn. */
  isActive: boolean
  renderBlock: (args: { block: ContentBlock; isStreaming: boolean }) => ReactNode
  sessionId?: string
  latestMCPAppBlockIds?: Set<string>
  compact?: boolean
}

function activityContentKey(blocks: ContentBlock[]): string {
  const last = blocks.at(-1)
  return [
    blocks.length,
    last?.id ?? '',
    last?.content.length ?? 0,
    last?.toolOutput?.length ?? 0,
    last?.toolDone ? 'done' : 'open',
  ].join(':')
}

export function ActivityTimeline({
  blocks,
  isActive,
  renderBlock,
}: ActivityTimelineProps) {
  const [open, setOpen] = useState(false)
  const toolBlocks = useMemo(
    () => blocks.filter((block) => block.type === 'tool' && block.toolName),
    [blocks],
  )
  const label = toolBlocks.length > 0
    ? groupLabel(toolBlocks)
    : isActive ? 'Thinking' : 'Thought'
  const actionLabel = `${blocks.length} ${blocks.length === 1 ? 'activity' : 'activities'}`
  const easdReviewTarget = [...toolBlocks]
    .reverse()
    .map((block) => easdToolReviewTarget(block.toolName, block.toolArgs, block.toolResult))
    .find((target) => target !== null) ?? null
  const contentKey = activityContentKey(blocks)
  const {
    contentRef,
    scrollRef,
    scrollToBottom,
    sentinelRef,
    showScrollButton: showLatest,
  } = usePinnedTranscript({
    isEmpty: blocks.length === 0,
    contentKey,
    resetKey: blocks[0]?.id,
    isolateScroll: true,
    followEnabled: open && isActive,
  })

  // Every group starts collapsed, live or historical: a run in progress should
  // read as one quiet summary row rather than unfolding the transcript on its
  // own. Opening is the reader's decision, and it survives every later delta
  // and the transition to commentary/completion.

  const toggleOpen = () => {
    if (open) {
      setOpen(false)
      return
    }

    setOpen(true)
    requestAnimationFrame(() => {
      if (isActive) scrollToBottom(false)
      else if (scrollRef.current) scrollRef.current.scrollTop = 0
    })
  }

  if (blocks.length === 0) return null

  return (
    <section className="activity-timeline min-w-0" aria-label="Agent activity">
      <button
        type="button"
        onClick={toggleOpen}
        className={cn(
          'flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-xs',
          'text-(--color-text-muted) transition-colors hover:bg-(--bg-key)',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)',
        )}
        aria-expanded={open}
        aria-label={`${open ? 'Collapse' : 'Expand'} ${label}, ${actionLabel}`}
      >
        <ChevronRight
          size={12}
          className={cn('shrink-0 transition-transform', open && 'rotate-90')}
          aria-hidden="true"
        />
        {/* No per-group running badge: the turn status line directly below
            already says what is running, for how long, and at what cost. */}
        <span className="min-w-0 truncate font-medium text-(--color-text-2)">{label}</span>
      </button>

      {easdReviewTarget && (
        <div className="flex flex-col gap-2 border-t border-(--color-border) px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-(--color-text-muted)">Draft persisted · user review is the next EASD step.</p>
          <EasdToolReviewAction target={easdReviewTarget} />
        </div>
      )}

      <div className="relative min-w-0" hidden={!open}>
          <div
            ref={scrollRef}
            role="log"
            aria-label="Activity history"
            aria-live={isActive ? 'polite' : 'off'}
            className="activity-timeline-scroll px-1"
          >
            <div ref={contentRef}>
              {blocks.map((block) => {
                const itemIsStreaming = isActive && block.id === blocks.at(-1)?.id
                return (
                  <BlockEnter key={block.id} disabled={itemIsStreaming && block.type === 'thinking'}>
                    <div className="activity-group-row">
                      {renderBlock({ block, isStreaming: itemIsStreaming })}
                    </div>
                  </BlockEnter>
                )
              })}
            </div>
            {/* Visibility of this is how the viewport knows it is at the
                bottom, so nothing measures the scroller to find out. */}
            <div
              ref={sentinelRef}
              aria-hidden="true"
              className="h-px w-full shrink-0 [overflow-anchor:none]"
            />

          {showLatest && isActive && (
            <button
              type="button"
              onClick={() => scrollToBottom(true)}
              className="absolute right-2 bottom-2 inline-flex items-center gap-1 rounded-full border border-(--color-border) bg-(--bg-card)/95 px-2 py-1 text-[11px] text-(--color-text-2) shadow-sm backdrop-blur hover:bg-(--bg-key) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)"
              aria-label="Latest activity"
            >
              <ChevronDown size={11} aria-hidden="true" />
              Latest activity
            </button>
          )}
          </div>
      </div>
    </section>
  )
}
