import type { ContentBlock } from '@/api/types'
import { isDirectUserBlock } from '@/utils/blocks'

interface PendingActivityInput {
  currentBlocks: ContentBlock[]
  isContinuing: boolean
  isError: boolean
  isWorking: boolean
}

/**
 * Whether the transcript needs a new-turn Thinking runway.
 *
 * Internal team transport can be represented as user-shaped blocks, but it
 * must never look like a fresh prompt or create a second runway below the
 * durable delegation cards.
 */
export function shouldShowPendingActivity({
  currentBlocks,
  isContinuing,
  isError,
  isWorking,
}: PendingActivityInput): boolean {
  const hasDirectUser = currentBlocks.some(isDirectUserBlock)
  if (!isWorking) return !isError && hasDirectUser
  if (isContinuing && currentBlocks.length === 0) return true
  return hasDirectUser && currentBlocks.every((block) => block.type === 'user')
}
