/**
 * Turn partitioning for assistant chat streams.
 *
 * A "turn" is a contiguous run of non-user blocks (thinking / tool / text).
 * User blocks are their own items. Used to render one footer (copy + time)
 * per assistant turn, regardless of how many internal blocks the turn has.
 */
import type { ContentBlock } from '@/api/types'
import { isConsolidatedDelegationMessage } from '@/utils/blocks'
import { extractSleepPrefix } from '@/utils/format'

export type TurnItem =
  | { kind: 'user'; block: ContentBlock; index: number }
  | { kind: 'assistant'; blocks: ContentBlock[]; startIndex: number }

export interface VisibleTurnWindow {
  hiddenTurnCount: number
  visibleTurnItems: TurnItem[]
}

function consolidateDelegationWaitPhase(blocks: ContentBlock[]): ContentBlock[] {
  const hiddenTextIndexes = new Set<number>()
  let delegationIndex = -1

  blocks.forEach((block, index) => {
    if (block.type === 'tool' && block.toolName === 'team_delegate') {
      delegationIndex = index
      return
    }
    if (
      delegationIndex >= 0
      && block.type === 'text'
      && extractSleepPrefix(block.content) !== null
    ) {
      for (let candidate = delegationIndex + 1; candidate <= index; candidate++) {
        if (blocks[candidate]?.type === 'text') hiddenTextIndexes.add(candidate)
      }
      delegationIndex = -1
    }
  })

  return hiddenTextIndexes.size > 0
    ? blocks.filter((_, index) => !hiddenTextIndexes.has(index))
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
  const hiddenTurnCount = Math.max(0, turnItems.length - renderedTurnCount)
  return {
    hiddenTurnCount,
    visibleTurnItems: hiddenTurnCount > 0 ? turnItems.slice(hiddenTurnCount) : turnItems,
  }
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
    const visibleTurnBlocks = consolidateDelegationWaitPhase(turnBlocks)
    if (visibleTurnBlocks.length > 0) {
      items.push({ kind: 'assistant', blocks: visibleTurnBlocks, startIndex })
    }
  }
  return items
}
