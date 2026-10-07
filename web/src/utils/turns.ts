/**
 * Turn partitioning for assistant chat streams.
 *
 * A "turn" is a contiguous run of non-user blocks (thinking / tool / text).
 * User blocks are their own items. Used to render one footer (copy + time)
 * per assistant turn, regardless of how many internal blocks the turn has.
 */
import type { ContentBlock } from '@/api/types'
import { isConsolidatedDelegationMessage } from '@/utils/blocks'

export type TurnItem =
  | { kind: 'user'; block: ContentBlock; index: number }
  | { kind: 'assistant'; blocks: ContentBlock[]; startIndex: number }

export interface VisibleTurnWindow {
  hiddenTurnCount: number
  visibleTurnItems: TurnItem[]
}

/**
 * Hide what the reader should not have to wade through while an agent waits.
 *
 * `sleep` is control state, so its tool block is never shown. When it follows a
 * `team_delegate`, the "work is underway" prose written in between is hidden
 * too: the delegation card already says it.
 */
function hideWaitPhase(blocks: ContentBlock[]): ContentBlock[] {
  const hiddenIndexes = new Set<number>()
  let delegationIndex = -1

  blocks.forEach((block, index) => {
    if (block.type !== 'tool') return
    if (block.toolName === 'team_delegate') {
      delegationIndex = index
      return
    }
    if (block.toolName !== 'sleep') return
    hiddenIndexes.add(index)
    if (delegationIndex >= 0) {
      for (let candidate = delegationIndex + 1; candidate < index; candidate++) {
        if (blocks[candidate]?.type === 'text') hiddenIndexes.add(candidate)
      }
      delegationIndex = -1
    }
  })

  return hiddenIndexes.size > 0
    ? blocks.filter((_, index) => !hiddenIndexes.has(index))
    : blocks
}

/** Only the newest rendered item in the trailing live turn may animate. */
export function isLatestStreamingItem(
  turnIsStreaming: boolean,
  itemIndex: number,
  itemCount: number,
): boolean {
  return turnIsStreaming && itemCount > 0 && itemIndex === itemCount - 1
}

export function getVisibleTurnWindow(
  turnItems: TurnItem[],
  renderedTurnCount: number,
): VisibleTurnWindow {
  let hiddenTurnCount = Math.max(0, turnItems.length - renderedTurnCount)

  // Never cut the render window between a prompt and its response. Otherwise
  // scrolling to the lazy-render boundary can show an assistant answer while
  // the user message that started that turn remains hidden just above it.
  if (
    hiddenTurnCount > 0
    && turnItems[hiddenTurnCount]?.kind === 'assistant'
    && turnItems[hiddenTurnCount - 1]?.kind === 'user'
  ) {
    hiddenTurnCount -= 1
  }

  return {
    hiddenTurnCount,
    visibleTurnItems: hiddenTurnCount > 0 ? turnItems.slice(hiddenTurnCount) : turnItems,
  }
}

/**
 * Append a hot live buffer to memoized finalized turns without repartitioning
 * the full history on every streamed delta. A contiguous assistant boundary is
 * merged so its React key and footer lifecycle stay stable on completion.
 */
export function appendLiveTurnItems(
  finalized: TurnItem[],
  currentBlocks: ContentBlock[],
  finalizedBlockCount: number,
): TurnItem[] {
  if (currentBlocks.length === 0) return finalized

  const live = partitionTurns(currentBlocks).map((item): TurnItem =>
    item.kind === 'user'
      ? { ...item, index: item.index + finalizedBlockCount }
      : { ...item, startIndex: item.startIndex + finalizedBlockCount },
  )
  const lastFinalized = finalized.at(-1)
  const firstLive = live[0]

  if (lastFinalized?.kind === 'assistant' && firstLive?.kind === 'assistant') {
    return [
      ...finalized.slice(0, -1),
      {
        kind: 'assistant',
        blocks: [...lastFinalized.blocks, ...firstLive.blocks],
        startIndex: lastFinalized.startIndex,
      },
      ...live.slice(1),
    ]
  }

  return [...finalized, ...live]
}

export function partitionTurns(blocks: ContentBlock[]): TurnItem[] {
  const items: TurnItem[] = []
  let i = 0
  while (i < blocks.length) {
    const b = blocks[i]
    if (isConsolidatedDelegationMessage(b)) {
      i++
      continue
    }
    if (b.type === 'user') {
      items.push({ kind: 'user', block: b, index: i })
      i++
      continue
    }
    const startIndex = i
    const turnBlocks: ContentBlock[] = []
    while (i < blocks.length) {
      const block = blocks[i]
      if (isConsolidatedDelegationMessage(block)) {
        i++
        continue
      }
      if (block.type === 'user') break
      turnBlocks.push(block)
      i++
    }
    const visibleTurnBlocks = hideWaitPhase(turnBlocks)
    if (visibleTurnBlocks.length > 0) {
      items.push({ kind: 'assistant', blocks: visibleTurnBlocks, startIndex })
    }
  }
  return items
}
