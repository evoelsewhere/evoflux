import { useMemo, type ReactNode } from 'react'

import { ActivityTimeline } from './ActivityTimeline'
import { BlockEnter } from './motion/BlockEnter'
import { segmentAssistantTurn } from '@/utils/activity-timeline'
import type { ContentBlock } from '@/api/types'

interface AssistantTurnContentProps {
  blocks: ContentBlock[]
  turnIsStreaming: boolean
  renderBlock: (args: {
    block: ContentBlock
    isStreaming: boolean
    isLast: boolean
  }) => ReactNode
  sessionId?: string
  latestMCPAppBlockIds?: Set<string>
  compact?: boolean
}

/**
 * The single chronological renderer for assistant turns on every chat surface.
 * Stable, content-delimited activity segments prevent streamed events from
 * being re-parented as the turn grows.
 */
export function AssistantTurnContent({
  blocks,
  turnIsStreaming,
  renderBlock,
  sessionId,
  latestMCPAppBlockIds,
  compact = false,
}: AssistantTurnContentProps) {
  const segments = useMemo(() => segmentAssistantTurn(blocks), [blocks])
  const lastBlock = blocks.at(-1)

  return segments.map((segment) => {
    const first = segment.blocks[0]
    if (!first) return null

    if (segment.kind === 'activity') {
      return (
        <ActivityTimeline
          key={`activity-${first.id}`}
          blocks={segment.blocks}
          isActive={turnIsStreaming && segment.blocks.at(-1)?.id === lastBlock?.id}
          sessionId={sessionId}
          latestMCPAppBlockIds={latestMCPAppBlockIds}
          compact={compact}
          renderBlock={({ block, isStreaming }) => renderBlock({
            block,
            isStreaming,
            isLast: block.id === lastBlock?.id,
          })}
        />
      )
    }

    return segment.blocks.map((block) => {
      const isStreaming = turnIsStreaming && block.id === lastBlock?.id
      return (
        <BlockEnter key={block.id} disabled={isStreaming && block.type === 'text'}>
          {renderBlock({ block, isStreaming, isLast: block.id === lastBlock?.id })}
        </BlockEnter>
      )
    })
  })
}
