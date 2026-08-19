import type { AgentUsage, ChatMessage, ContentBlock, MessageResponse } from '@/api/types'
import { generateBlockId } from './blocks'

// Me sort messages by timestamp asc, assistant before tool on ties

function continuationSeparator(left: string, right: string): string {
  if (!left || !right) return ''
  if (/\s$/.test(left) || /^\s/.test(right)) return ''
  return ' '
}

function shellDisplayContent(msg: MessageResponse): string {
  const command = msg.extra?.command
  if (msg.extra?.kind === 'user_shell' && typeof command === 'string' && command.trim()) {
    return command.trim().startsWith('!') ? command.trim() : `!${command.trim()}`
  }
  // WebBridge stores browser evidence in the canonical message body so the
  // agent receives one fenced prompt. Both EvoFlux Chat and Side Chat should
  // render the user's original request, not that internal transport envelope.
  const sidePanel = msg.extra?.webbridge_side_panel
  if (sidePanel && typeof sidePanel === 'object' && !Array.isArray(sidePanel)) {
    const userContent = (sidePanel as Record<string, unknown>).user_content
    if (typeof userContent === 'string' && userContent.trim()) return userContent
  }
  return msg.content || ''
}

function sortMessages(msgs: MessageResponse[]): MessageResponse[] {
  return [...msgs].sort((a, b) => {
    const ta = a.created_at ? new Date(a.created_at).getTime() : 0
    const tb = b.created_at ? new Date(b.created_at).getTime() : 0
    if (ta !== tb) return ta - tb
    const roleOrder: Record<string, number> = { user: 0, assistant: 1, tool: 2, system: 3 }
    return (roleOrder[a.role] ?? 9) - (roleOrder[b.role] ?? 9)
  })
}

// Me extract ContentBlock[] from one assistant MessageResponse
function assistantBlocks(
  msg: MessageResponse,
  pendingToolBlocks: Map<string, ContentBlock>,
  timestamp?: Date,
): ContentBlock[] {
  const blocks: ContentBlock[] = []

  if (msg.reasoning_content && !msg.extra?.is_continuation) {
    blocks.push({ id: generateBlockId(), type: 'thinking', content: msg.reasoning_content, timestamp })
  }

  const extra = msg.extra as { duration_ms?: number; model?: unknown; lifecycle?: unknown } | null
  const responseDurationMs = typeof extra?.duration_ms === 'number' ? extra.duration_ms : undefined
  const model = typeof extra?.model === 'string' ? extra.model : undefined
  const lifecycle = extra?.lifecycle === 'sleep' ? 'sleep' : undefined

  // Me text before tools — LLM emits content first, then tool_calls
  if (msg.content || lifecycle) {
    blocks.push({
      id: generateBlockId(),
      type: 'text',
      content: msg.content || '',
      timestamp,
      responseDurationMs,
      extra: model || lifecycle ? { ...(model ? { model } : {}), ...(lifecycle ? { lifecycle } : {}) } : undefined,
    })
  }

  for (const tool of (msg.tool_calls ?? []).filter((t) => t.function?.name !== 'todo_manage')) {
    const name = tool.function?.name ?? tool.id
    let parsedArgs: Record<string, unknown> | undefined
    let args: string | undefined
    try {
      parsedArgs = JSON.parse(tool.function?.arguments ?? '{}')
      args = JSON.stringify(parsedArgs, null, 2)
    } catch {
      args = tool.function?.arguments ?? undefined
    }

    // show_widget's own arguments carry the full widget HTML — reconstruct
    // the widget block from history instead of falling back to a generic
    // collapsed tool-call chip (the streamed widgetHtml never persists).
    if (name === 'show_widget' && typeof parsedArgs?.widget_code === 'string') {
      const block: ContentBlock = {
        id: generateBlockId(),
        type: 'widget',
        content: '',
        toolCallId: tool.id,
        widgetHtml: parsedArgs.widget_code,
        isStreaming: false,
        title: typeof parsedArgs.title === 'string' ? parsedArgs.title : 'Widget',
        timestamp,
      }
      blocks.push(block)
      if (tool.id) pendingToolBlocks.set(tool.id, block)
      continue
    }

    const block: ContentBlock = {
      id: generateBlockId(),
      type: 'tool',
      content: '',
      toolName: name,
      toolArgs: args,
      toolCallId: tool.id,
      toolDone: false,
      timestamp,
    }
    blocks.push(block)
    if (tool.id) pendingToolBlocks.set(tool.id, block)
  }

  return blocks
}

/**
 * Parse DB messages into ChatMessage[] — used by single-agent chat view.
 * User messages → ChatMessage{role:'user'}
 * Assistant messages → ChatMessage{role:'assistant', blocks:[...]}
 * Tool result messages → mutate matching tool block (toolDone=true, toolResult=...)
 */
export function parseApiMessages(msgs: MessageResponse[]): ChatMessage[] {
  const result: ChatMessage[] = []
  const pendingToolBlocks: Map<string, ContentBlock> = new Map()

  for (const msg of sortMessages(msgs)) {
    // Summaries surface as an inline "Session compacted" divider rather
    // than being hidden from the chat — gives users a visible marker of
    // where context compaction happened.
    if (msg.is_summary) {
      const timestamp = msg.created_at ? new Date(msg.created_at) : new Date()
      result.push({
        id: msg.id,
        role: 'assistant',
        content: '',
        blocks: [{
          id: generateBlockId(),
          type: 'compaction',
          content: '',
          extra: { state: 'compacted' },
          timestamp,
        }],
        agent: msg.name || undefined,
        timestamp,
      })
      continue
    }

    if (msg.role === 'user') {
      result.push({
        id: msg.id,
        role: 'user',
        content: shellDisplayContent(msg),
        blocks: [],
        timestamp: msg.created_at ? new Date(msg.created_at) : new Date(),
        attachments: msg.attachments ?? undefined,
      })
      continue
    }

    if (msg.role === 'tool' && msg.tool_call_id) {
      const block = pendingToolBlocks.get(msg.tool_call_id)
      const extra = msg.extra
      if (block) {
        block.toolResult = msg.content || ''
        block.toolDone = true
        if (typeof extra?.duration_ms === 'number') block.durationMs = extra.duration_ms
        if (extra) block.extra = { ...(block.extra ?? {}), ...extra }
      }
      continue
    }

    if (msg.role === 'assistant') {
      const timestamp = msg.created_at ? new Date(msg.created_at) : new Date()
      const blocks = assistantBlocks(msg, pendingToolBlocks, timestamp)
      const extra = msg.extra as { usage?: { input?: number; output?: number; cache?: number } } | null
      const usage = extra?.usage ? {
        promptTokens: extra.usage.input ?? 0,
        completionTokens: extra.usage.output ?? 0,
        totalTokens: (extra.usage.input ?? 0) + (extra.usage.output ?? 0),
        cachedTokens: extra.usage.cache ?? 0,
      } : undefined
      result.push({
        id: msg.id,
        role: 'assistant',
        content: '',
        blocks,
        agent: msg.name || undefined,
        timestamp,
        usage,
      })
    }
  }

  return result
}

/**
 * Aggregate token usage across all assistant messages in a list.
 * Rules: input = last turn, output = sum all turns, cache = last turn.
 * Reads from message.extra.usage persisted by DatabaseHook.
 */
export function sumUsageFromMessages(msgs: MessageResponse[]): AgentUsage {
  const acc = { promptTokens: 0, completionTokens: 0, totalTokens: 0, cachedTokens: 0 }
  let lastInput = 0
  let lastCache = 0
  for (const msg of sortMessages(msgs)) {
    if (msg.role !== 'assistant') continue
    const extra = msg.extra as { usage?: { input?: number; output?: number; cache?: number } } | null
    if (!extra?.usage) continue
    const i = extra.usage.input ?? 0
    const o = extra.usage.output ?? 0
    acc.completionTokens += o
    lastInput = i
    lastCache = extra.usage.cache ?? 0
  }
  acc.promptTokens = lastInput
  acc.cachedTokens = lastCache
  acc.totalTokens  = lastInput + acc.completionTokens
  return acc
}

/**
 * Parse DB messages into a flat ContentBlock[] — used by team agent/split view.
 * User messages → type:'user' block (rendered as user bubble inline)
 * Assistant messages → thinking/tool/text blocks
 * Tool result messages → mutate matching tool block
 */
export function parseTeamBlocks(msgs: MessageResponse[]): ContentBlock[] {
  const result: ContentBlock[] = []
  const pendingToolBlocks: Map<string, ContentBlock> = new Map()

  for (const msg of sortMessages(msgs)) {
    if (msg.extra?.queue_status === 'queued') continue

    // Summaries surface as inline "Session compacted" dividers rather than
    // being hidden — preserves the visual marker across page reloads.
    if (msg.is_summary) {
      const timestamp = msg.created_at ? new Date(msg.created_at) : new Date()
      result.push({
        id: msg.id,
        type: 'compaction',
        content: '',
        extra: { state: 'compacted' },
        timestamp,
      })
      continue
    }

    if (msg.role === 'user') {
      // Me normalise DB extra: support both old (from_agents: string[]) and new (from_agent: string) formats
      const rawExtra = msg.extra as { routing?: { from_agent?: string; from_agents?: string[] }; from_agent?: string; from_agents?: string[] } | null
      const fromAgent = rawExtra?.from_agent ?? rawExtra?.routing?.from_agent ?? rawExtra?.from_agents?.[0] ?? rawExtra?.routing?.from_agents?.[0]
      const extra = { ...(msg.extra ?? {}) }
      if (fromAgent) extra.from_agent = fromAgent
      const timestamp = msg.created_at ? new Date(msg.created_at) : new Date()
      result.push({
        id: msg.id,
        type: 'user',
        content: shellDisplayContent(msg),
        extra: Object.keys(extra).length > 0 ? extra : undefined,
        timestamp,
        attachments: msg.attachments ?? undefined,
      })
      continue
    }

    if (msg.role === 'tool' && msg.tool_call_id) {
      const block = pendingToolBlocks.get(msg.tool_call_id)
      const extra = msg.extra
      if (block) {
        block.toolResult = msg.content || ''
        block.toolDone = true
        if (typeof extra?.duration_ms === 'number') block.durationMs = extra.duration_ms
        if (extra) block.extra = { ...(block.extra ?? {}), ...extra }
      }
      continue
    }

    if (msg.role === 'assistant') {
      const timestamp = msg.created_at ? new Date(msg.created_at) : new Date()
      for (const block of assistantBlocks(msg, pendingToolBlocks, timestamp)) {
        const lastBlock = result[result.length - 1]
        if (msg.extra?.is_continuation && block.type === 'text' && lastBlock?.type === 'text') {
          lastBlock.content += continuationSeparator(lastBlock.content, block.content) + block.content
        } else {
          result.push(block)
        }
      }
    }
  }

  return result
}
