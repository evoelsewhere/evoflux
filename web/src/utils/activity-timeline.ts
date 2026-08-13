import type { ContentBlock } from '@/api/types'

export interface AssistantActivityPartition {
  activityBlocks: ContentBlock[]
  answerBlocks: ContentBlock[]
}

/**
 * Keep the chronological work trace intact through the latest thinking/tool
 * block. Thought remains its own rendered block; only consecutive tool calls
 * are grouped. Trailing answer prose renders outside the bounded timeline.
 */
export function partitionAssistantActivity(blocks: ContentBlock[]): AssistantActivityPartition {
  let lastActivityIndex = -1
  for (let index = blocks.length - 1; index >= 0; index--) {
    if (blocks[index].type === 'thinking' || blocks[index].type === 'tool') {
      lastActivityIndex = index
      break
    }
  }

  if (lastActivityIndex < 0) return { activityBlocks: [], answerBlocks: blocks }
  return {
    activityBlocks: blocks.slice(0, lastActivityIndex + 1),
    answerBlocks: blocks.slice(lastActivityIndex + 1),
  }
}
