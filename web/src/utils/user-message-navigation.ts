import type { MessageAttachment } from '@/api/types'
import type { TurnItem } from '@/utils/turns'

export interface UserMessageNavigationItem {
  id: string
  label: string
  response: string
  toolNames: string[]
  turnIndex: number
}

function attachmentLabel(attachments: MessageAttachment[] | undefined): string {
  if (!attachments?.length) return ''
  return attachments
    .map((attachment) => attachment.original_name ?? attachment.filename ?? '')
    .filter(Boolean)
    .join(', ')
}

function responsePreview(content: string): string {
  const [firstBlock = ''] = content.trim().split(/\n[ \t]*\n/, 1)

  return firstBlock
    .replace(/```(?:[^\n]*)\n?([\s\S]*?)```/g, '$1')
    .replace(/^\s{0,3}#{1,6}[ \t]+/gm, '')
    .replace(/^\s{0,3}>[ \t]?/gm, '')
    .replace(/^\s{0,3}(?:[-+*]|\d+[.)])[ \t]+/gm, '')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/(\*\*|__)(.*?)\1/g, '$2')
    .replace(/~~(.*?)~~/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * Build the prompt rail from direct user messages only.
 *
 * Agent-to-agent inbox messages use the same `user` block variant in the
 * transcript, but they are not prompts authored by the person using EvoFlux.
 * Any user-shaped block still ends the response associated with the previous
 * prompt, matching the turn boundary visible in the transcript.
 */
export function buildUserMessageNavigationItems(
  turnItems: TurnItem[],
): UserMessageNavigationItem[] {
  const items: UserMessageNavigationItem[] = []
  let current: UserMessageNavigationItem | null = null

  for (const [turnIndex, turn] of turnItems.entries()) {
    if (turn.kind === 'user') {
      current = null
      if (turn.block.extra?.from_agent) continue

      const label = turn.block.content.trim() || attachmentLabel(turn.block.attachments)
      if (!label) continue

      current = {
        id: turn.block.id,
        label,
        response: '',
        toolNames: [],
        turnIndex,
      }
      items.push(current)
      continue
    }

    if (!current) continue
    for (const block of turn.blocks) {
      // A response can contain several prose blocks separated by tool calls.
      // The final prose block is the closest equivalent to Codex's response
      // preview and avoids exposing internal thinking/tool output.
      if (block.type === 'text' && block.content.trim()) {
        current.response = responsePreview(block.content)
      } else if (block.type === 'tool' && block.toolName) {
        if (!current.toolNames.includes(block.toolName)) {
          current.toolNames.push(block.toolName)
        }
      }
    }
  }

  return items
}
