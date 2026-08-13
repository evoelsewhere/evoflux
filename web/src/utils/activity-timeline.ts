import type { ContentBlock } from '@/api/types'

export type AssistantTurnSegment =
  | { kind: 'activity'; blocks: ContentBlock[] }
  | { kind: 'content'; blocks: ContentBlock[] }

export function isActivityBlock(block: ContentBlock): boolean {
  // Delegation cards are durable, live task surfaces. Keeping them inside the
  // bounded activity log clips larger teams and freezes their scroll position
  // when the lead sleeps while members continue working.
  return block.type === 'thinking'
    || (block.type === 'tool' && block.toolName !== 'team_delegate')
}

/**
 * Partition a turn without ever moving an already-rendered block to a new
 * parent when a later event arrives. Text/widget/status blocks remain transcript
 * content; only adjacent thinking/tool events form an activity group.
 *
 * This mirrors the semantic stream: commentary and output are content, while
 * reasoning and ordinary tool lifecycle events are activity. Durable team
 * delegation cards are content so they remain fully visible outside the
 * bounded work log. A content event is a hard group boundary, so later tools
 * start a new group instead of swallowing the preceding commentary into a
 * growing work log.
 */
export function segmentAssistantTurn(blocks: ContentBlock[]): AssistantTurnSegment[] {
  const segments: AssistantTurnSegment[] = []

  for (const block of blocks) {
    const kind = isActivityBlock(block) ? 'activity' : 'content'
    const previous = segments.at(-1)
    if (previous?.kind === kind) {
      previous.blocks.push(block)
    } else {
      segments.push({ kind, blocks: [block] } as AssistantTurnSegment)
    }
  }

  return segments
}
