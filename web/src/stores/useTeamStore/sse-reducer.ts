import {
  appendThinking,
  appendText,
  initTool,
  addTool,
  appendToolOutput,
  completeTool,
  generateBlockId,
  startCompaction,
  endCompaction,
} from '@/utils/blocks'
import { createDefaultAgentStream } from './defaults'
import {
  WIKI_MUTATING_TOOLS,
  FS_MUTATING_TOOLS,
  NOTE_TOOLS,
  SCHEDULER_MUTATING_TOOLS,
  TODO_MUTATING_TOOLS,
  extractToolPaths,
  touchesWiki,
} from './helpers'
import { isBackgroundCompletion, sendDesktopNotification } from '@/lib/desktop-notifications'
import type { GoalResponse, TurnChangedFile, TurnCost, TurnUsage, TurnUsageBreakdown } from '@/api/types'
import type { ActivityItem, CacheInvalidation, TeamStore } from './types'

type Setter = (fn: (draft: TeamStore) => void) => void
type Getter = () => TeamStore

function compactSessionId(sessionId: string | null): string | null {
  return sessionId ? sessionId.slice(0, 8) : null
}

function workspaceName(workspace: string | null): string | null {
  if (!workspace) return null
  return workspace.split('/').filter(Boolean).at(-1) ?? workspace
}

function sessionLabel(state: TeamStore): string {
  const title = state.sessionTitle?.trim()
  const id = compactSessionId(state.sessionId)
  return title || (id ? `Session ${id}` : 'this session')
}

function codingWorkspaceSuffix(state: TeamStore): string {
  const name = workspaceName(state._workspace)
  return name ? ` - ${name}` : ''
}

function ensureAgent(draft: TeamStore, agent: string) {
  if (!draft.agentStreams[agent]) draft.agentStreams[agent] = createDefaultAgentStream()
  if (!draft.agentNames.includes(agent)) draft.agentNames.push(agent)
}

const MAX_ACTIVITY_ITEMS = 200

function pushActivity(draft: TeamStore, item: Omit<ActivityItem, 'id' | 'timestamp'>) {
  draft.activityLog.push({ ...item, id: generateBlockId(), timestamp: new Date() })
  if (draft.activityLog.length > MAX_ACTIVITY_ITEMS) {
    draft.activityLog = draft.activityLog.slice(-MAX_ACTIVITY_ITEMS)
  }
}

interface CreateSSEHandlerArgs {
  set: Setter
  get: Getter
}

type BufferedTextKind = 'message' | 'thinking'

function stampOpenTextBlocks(
  blocks: TeamStore['agentStreams'][string]['currentBlocks'],
  completedAt: number,
  turnStartedAt?: number | null,
) {
  return blocks.map((block) => {
    if (block.type !== 'text' || block.responseDurationMs !== undefined) return block
    const startedAt = turnStartedAt ?? block.startedAt
    if (startedAt === undefined || startedAt === null) return block
    return {
      ...block,
      responseDurationMs: Math.max(0, completedAt - startedAt),
    }
  })
}

/**
 * Put the turn's spend on the block the footer reads.
 *
 * Live, tokens and cost arrive as their own SSE event and land in the
 * agent's usage; the footer only sees blocks. Stamping the last text block
 * at turn end means the footer reads the same field live and after a
 * reload, where the value comes back on the message instead.
 */
function stampTurnUsage(
  blocks: TeamStore['agentStreams'][string]['currentBlocks'],
  usage: TeamStore['agentStreams'][string]['usage'],
) {
  const input = usage.turnPromptTokens ?? 0
  const output = usage.turnCompletionTokens ?? 0
  if (input === 0 && output === 0) return blocks
  const lastText = blocks.map((block) => block.type).lastIndexOf('text')
  if (lastText === -1) return blocks
  const turnUsage: TurnUsage = {
    input,
    output,
    cache: usage.turnCachedTokens,
    cache_write: usage.turnCacheWriteTokens,
    calls: usage.turnCalls,
    cost: usage.turnCost,
  }
  return blocks.map((block, index) =>
    index === lastText ? { ...block, turnUsage } : block,
  )
}

function markTurnStarted(draft: TeamStore, agent: string, startedAt = Date.now()) {
  ensureAgent(draft, agent)
  const stream = draft.agentStreams[agent]
  if (stream._turnStartedAt === undefined || stream._turnStartedAt === null) {
    resetTurnUsage(stream)
    stream._turnStartedAt = startedAt
  }
}

function resetTurnUsage(stream: TeamStore['agentStreams'][string]) {
  stream.usage.turnPromptTokens = 0
  stream.usage.turnCompletionTokens = 0
  stream.usage.turnTotalTokens = 0
  stream.usage.turnCachedTokens = 0
  stream.usage.turnCacheWriteTokens = 0
  stream.usage.turnCalls = 0
  stream.usage.turnCost = undefined
  stream.usage.turnPhases = {}
  stream._turnCompletionEstimated = 0
}

function appendStreamingText(
  draft: TeamStore,
  agent: string,
  kind: BufferedTextKind,
  text: string,
  model?: string | null,
  lifecycle?: string | null,
) {
  ensureAgent(draft, agent)
  const stream = draft.agentStreams[agent]
  if (stream._turnStartedAt === undefined || stream._turnStartedAt === null) {
    resetTurnUsage(stream)
    stream._turnStartedAt = Date.now()
  }
  if (kind === 'thinking') {
    stream.currentBlocks = appendThinking(stream.currentBlocks, text)
    const last = stream.currentBlocks[stream.currentBlocks.length - 1]
    if (last?.type === 'thinking' && !last.startedAt) last.startedAt = Date.now()
  } else {
    stream.currentBlocks = appendText(stream.currentBlocks, text)
    const last = stream.currentBlocks[stream.currentBlocks.length - 1]
    if (last?.type === 'text') {
      if (!last.startedAt) last.startedAt = Date.now()
      if (model) last.extra = { ...(last.extra ?? {}), model }
      if (lifecycle) last.extra = { ...(last.extra ?? {}), lifecycle }
    }
  }
  if (text) {
    stream._completionEstimated = (stream._completionEstimated ?? 0) + (text.length / 4)
    const newEstimatedVal = Math.round(stream._completionEstimated)
    const currentTurnTokens = Math.max(stream.usage.completionTokens - stream._completionBase, newEstimatedVal)
    stream.usage.completionTokens = stream._completionBase + currentTurnTokens
    stream.usage.totalTokens = stream.usage.promptTokens + stream.usage.completionTokens

    // The authoritative turn total only lands when a model call *finishes*,
    // so without this the live counter froze for the whole of a long call —
    // the one stretch where a reader is actually watching it. The estimate
    // only ever raises the count; the next `usage` event assigns over it.
    stream._turnCompletionEstimated = (stream._turnCompletionEstimated ?? 0) + (text.length / 4)
    stream.usage.turnCompletionTokens = Math.max(
      stream.usage.turnCompletionTokens ?? 0,
      Math.round(stream._turnCompletionEstimated),
    )
    stream.usage.turnTotalTokens =
      (stream.usage.turnPromptTokens ?? 0) + stream.usage.turnCompletionTokens
  }
}

export function createSSEHandler({ set, get }: CreateSSEHandlerArgs) {
  return (type: string, data: unknown) => {
    const d = data as Record<string, unknown>

    switch (type) {
      case 'session': {
        set((draft) => { draft.sessionId = d.session_id as string })
        break
      }

      case 'title_update': {
        set((draft) => { draft.sessionTitle = d.title as string })
        break
      }

      case 'thinking': {
        const agent = d.agent as string
        const text = d.text as string
        const meta = d.metadata as Record<string, unknown> | undefined
        set((draft) => {
          appendStreamingText(draft, agent, 'thinking', text, typeof meta?.model === 'string' ? meta.model : null)
        })
        break
      }

      case 'message': {
        const agent = d.agent as string
        const text = d.text as string
        const meta = d.metadata as Record<string, unknown> | undefined
        set((draft) => {
          appendStreamingText(
            draft,
            agent,
            'message',
            text,
            typeof meta?.model === 'string' ? meta.model : null,
            typeof meta?.lifecycle === 'string' ? meta.lifecycle : null,
          )
        })
        break
      }

      case 'tool_call': {
        if (TODO_MUTATING_TOOLS.has(d.name as string)) break
        const agent = d.agent as string
        set((draft) => {
          markTurnStarted(draft, agent)
          draft.agentStreams[agent].currentBlocks = initTool(
            draft.agentStreams[agent].currentBlocks,
            d.name as string,
            d.tool_call_id as string | undefined,
            typeof d.duration_ms === 'number' ? d.duration_ms : undefined,
          )
        })
        break
      }

      case 'tool_start': {
        if (TODO_MUTATING_TOOLS.has(d.name as string)) break
        const agent = d.agent as string
        set((draft) => {
          markTurnStarted(draft, agent)
          draft.agentStreams[agent].currentBlocks = addTool(
            draft.agentStreams[agent].currentBlocks,
            d.name as string,
            d.arguments as string | undefined,
            d.tool_call_id as string | undefined,
            typeof d.duration_ms === 'number' ? d.duration_ms : undefined,
          )
        })
        break
      }

      case 'tool_output_delta': {
        if (TODO_MUTATING_TOOLS.has(d.name as string)) break
        const agent = d.agent as string
        set((draft) => {
          ensureAgent(draft, agent)
          draft.agentStreams[agent].currentBlocks = appendToolOutput(
            draft.agentStreams[agent].currentBlocks,
            d.name as string,
            d.tool_call_id as string | undefined,
            d.text as string,
          )
        })
        break
      }

      case 'widget_delta': {
        const agent = d.agent as string
        const toolCallId = d.tool_call_id as string
        const html = d.html as string
        const isFinal = d.is_final as boolean
        const metadata = d.metadata as Record<string, unknown> | undefined
        set((draft) => {
          ensureAgent(draft, agent)
          const stream = draft.agentStreams[agent]
          // Find or create widget block
          let widgetBlock = stream.currentBlocks.find(
            (b) => b.type === 'widget' && b.toolCallId === toolCallId
          )
          if (!widgetBlock) {
            widgetBlock = {
              type: 'widget',
              id: generateBlockId(),
              content: '',
              toolCallId,
              toolName: 'show_widget',
              startedAt: Date.now(),
              widgetHtml: '',
              isStreaming: true,
              title: (metadata?.title as string) || 'widget',
            }
            stream.currentBlocks.push(widgetBlock)
          }
          // Update HTML content
          widgetBlock.widgetHtml += html
          widgetBlock.isStreaming = !isFinal
        })
        break
      }

      case 'tool_end': {
        const agent = d.agent as string
        const toolName = d.name as string
        const toolCallId = d.tool_call_id as string | undefined
        const result = d.result as string | undefined
        const metadata = d.metadata as Record<string, unknown> | undefined
        const durationMs = typeof d.duration_ms === 'number'
          ? d.duration_ms
          : typeof metadata?.duration_ms === 'number'
            ? metadata.duration_ms
            : undefined
        const mcpApp = metadata?.mcp_app as Record<string, unknown> | undefined
        if (!TODO_MUTATING_TOOLS.has(toolName)) {
          set((draft) => {
            ensureAgent(draft, agent)
            draft.agentStreams[agent].currentBlocks = completeTool(
              draft.agentStreams[agent].currentBlocks,
              toolName,
              toolCallId,
              result,
              durationMs,
              metadata
                ? {
                    ...metadata,
                    ...(mcpApp ? { mcp_app: mcpApp } : {}),
                  }
                : undefined,
            )
          })
        }
        if (isBackgroundCompletion(toolName, result)) {
          const state = get()
          void sendDesktopNotification({
            kind: 'background_done',
            title: `Background task completed${codingWorkspaceSuffix(state)}`,
            body: sessionLabel(state),
          })
        }
        const events: CacheInvalidation[] = []
        if (NOTE_TOOLS.has(toolName)) {
          events.push({ kind: 'wiki' })
        }
        let touchedWiki = false
        if (WIKI_MUTATING_TOOLS.has(toolName)) {
          const stream = get().agentStreams[agent]
          const block = stream?.currentBlocks.find(
            (b) => b.type === 'tool' && (toolCallId ? b.toolCallId === toolCallId : b.toolName === toolName),
          )
          if (touchesWiki(toolName, block?.toolArgs)) {
            events.push({ kind: 'wiki' })
            touchedWiki = true
          }
        }
        if (FS_MUTATING_TOOLS.has(toolName) && !touchedWiki) {
          const workspace = get()._workspace
          if (workspace) {
            const stream = get().agentStreams[agent]
            const block = stream?.currentBlocks.find(
              (b) =>
                b.type === 'tool' &&
                (toolCallId ? b.toolCallId === toolCallId : b.toolName === toolName),
            )
            const paths = extractToolPaths(toolName, block?.toolArgs)
            const workspacePaths = paths?.filter(
              (p) => !p.startsWith('wiki/') && p !== 'wiki',
            )
            if (workspacePaths && workspacePaths.length > 0) {
              events.push({
                kind: 'coding_workspace_paths',
                workspace,
                paths: workspacePaths,
              })
            } else {
              events.push({ kind: 'coding_workspace', workspace })
            }
          } else {
            const sid = get().sessionId
            if (sid) events.push({ kind: 'workspace_files', sessionId: sid })
          }
        }
        if (SCHEDULER_MUTATING_TOOLS.has(toolName)) {
          events.push({ kind: 'scheduler' })
        }
        if (TODO_MUTATING_TOOLS.has(toolName)) {
          const sid = get().sessionId
          if (sid) events.push({ kind: 'todos', sessionId: sid })
        }
        if (toolName === 'team_manage') {
          events.push({ kind: 'team_agents' })
        }
        if (events.length > 0) {
          set((draft) => { draft.cacheInvalidations.push(...events) })
        }
        break
      }

      case 'provider_status': {
        const agent = d.agent as string
        const status = d.status as string
        if (!agent || !status) break
        set((draft) => {
          ensureAgent(draft, agent)
          draft.agentStreams[agent].currentBlocks.push({
            id: generateBlockId(),
            type: 'provider_status',
            content: '',
            extra: d,
            timestamp: new Date(),
          })
          if (status === 'fallback' && typeof d.fallback === 'string') {
            const textBlock = [...draft.agentStreams[agent].currentBlocks].reverse().find((block) => block.type === 'text')
            if (textBlock) textBlock.extra = { ...(textBlock.extra ?? {}), model: d.fallback }
          }
        })
        break
      }

      case 'usage': {
        const meta = d.metadata as Record<string, unknown> | undefined
        const agent = (meta?.agent as string) ?? (d.agent as string)
        if (!agent) break
        set((draft) => {
          ensureAgent(draft, agent)
          const stream = draft.agentStreams[agent]
          const u = stream.usage
          const promptTokens = (d.prompt_tokens as number) || 0
          const completionTokens = (d.completion_tokens as number) || 0
          const cachedTokens = d.cached_tokens as number | undefined
          const cacheWriteTokens = d.cache_write_tokens as number | undefined
          if (meta?.turn_total) {
            u.turnPromptTokens = promptTokens
            u.turnCompletionTokens = completionTokens
            u.turnTotalTokens = (d.total_tokens as number) || (promptTokens + completionTokens)
            u.turnCachedTokens = cachedTokens ?? 0
            u.turnCacheWriteTokens = cacheWriteTokens ?? 0
            u.turnCalls = typeof meta.calls === 'number' ? meta.calls : undefined
            u.turnPhases = meta.phases && typeof meta.phases === 'object'
              ? meta.phases as Record<string, TurnUsageBreakdown>
              : undefined
            u.turnCost = d.cost && typeof d.cost === 'object'
              ? d.cost as TurnCost
              : undefined
            // Snap the live estimate back onto the measured total, so the
            // next call's deltas extend a real number rather than a drift.
            stream._turnCompletionEstimated = completionTokens
            return
          }
          u.promptTokens     = promptTokens
          u.completionTokens = stream._completionBase + completionTokens
          u.cachedTokens     = cachedTokens ?? u.cachedTokens
          u.cacheWriteTokens = cacheWriteTokens ?? u.cacheWriteTokens
          u.totalTokens      = u.promptTokens + u.completionTokens
          stream._completionEstimated = completionTokens
        })
        break
      }

      case 'inbox': {
        const agent = d.agent as string
        const fromAgent = d.from_agent as string
        const artifact = d._handoff_artifact as Record<string, unknown> | undefined
        set((draft) => {
          ensureAgent(draft, agent)
          const extra: Record<string, unknown> = { from_agent: fromAgent }
          if (artifact) extra._handoff_artifact = artifact
          draft.agentStreams[agent].currentBlocks.push({
            id: generateBlockId(),
            type: 'user',
            content: d.content as string,
            extra,
            timestamp: new Date(),
          })
          pushActivity(draft, {
            kind: artifact ? 'handoff' : 'inbox',
            agent,
            label: artifact
              ? `Handoff from ${fromAgent}`
              : `Message from ${fromAgent}`,
            artifact: artifact ?? undefined,
            meta: { from_agent: fromAgent },
          })
        })
        break
      }

      case 'handoff': {
        const fromAgent = d.from_agent as string
        const toAgents = d.to_agents as string[]
        const artifact = d.artifact as Record<string, unknown> | undefined
        set((draft) => {
          pushActivity(draft, {
            kind: 'handoff',
            agent: fromAgent,
            label: `${fromAgent} → ${toAgents.join(', ')}`,
            artifact,
            meta: { from_agent: fromAgent, to_agents: toAgents },
          })
        })
        break
      }

      case 'delegation': {
        const fromAgent = (d.from as string) || 'lead'
        const toAgents = Array.isArray(d.to) ? (d.to as string[]) : []
        const title = typeof d.title === 'string' ? d.title : 'Delegated task'
        const taskIds = Array.isArray(d.task_ids) ? (d.task_ids as string[]) : []
        const spec = d.spec && typeof d.spec === 'object'
          ? (d.spec as Record<string, unknown>)
          : undefined
        set((draft) => {
          pushActivity(draft, {
            kind: 'delegation',
            agent: fromAgent,
            label: `Task → ${toAgents.join(', ') || 'agent'}: ${title}`,
            meta: { from_agent: fromAgent, to_agents: toAgents, task_ids: taskIds, title, spec },
          })
          for (const name of toAgents) {
            ensureAgent(draft, name)
            if (draft.agentStreams[name]) {
              draft.agentStreams[name].status = 'working'
            }
          }
        })
        break
      }

      case 'queued_turn_start': {
        const agent = d.agent as string
        const messageIds = Array.isArray(d.message_ids) ? new Set(d.message_ids as string[]) : null
        const eventMessages = Array.isArray(d.messages)
          ? (d.messages as Array<{ id?: unknown; content?: unknown }>).flatMap((msg) => {
              if (typeof msg.id !== 'string' || typeof msg.content !== 'string') return []
              return [{ id: msg.id, content: msg.content }]
            })
          : []
        set((draft) => {
          ensureAgent(draft, agent)
          if (agent !== draft.leadName || !draft.sessionId) return
          draft.isTeamWorking = true
          draft.isContinuing = false
          draft.error = null
          resetTurnUsage(draft.agentStreams[agent])
          draft.agentStreams[agent].status = 'working'
          const queued = draft._pendingMessages.filter((msg) => {
            if (msg.sessionId !== draft.sessionId) return false
            return messageIds === null || messageIds.has(msg.id)
          })
          const queuedIds = new Set(queued.map((msg) => msg.id))
          const messages = [
            ...queued.map((msg) => ({
              id: msg.id,
              content: msg.content,
              submittedAt: msg.submittedAt,
            })),
            ...eventMessages
              .filter((msg) => !queuedIds.has(msg.id))
              .map((msg) => ({
                ...msg,
                submittedAt: Date.now(),
              })),
          ]
          if (messages.length === 0) return
          const now = Date.now()
          const stream = draft.agentStreams[agent]
          stream.currentBlocks = stampOpenTextBlocks(
            stream.currentBlocks,
            now,
            stream._turnStartedAt,
          )
          const nextTurnStartedAt = messages[0]?.submittedAt ?? now
          stream.currentBlocks.push(
            ...messages.map((msg) => ({
              id: msg.id,
              type: 'user' as const,
              content: msg.content,
              timestamp: new Date(msg.submittedAt ?? now),
            })),
          )
          stream._turnStartedAt = nextTurnStartedAt
          draft._pendingMessages = draft._pendingMessages.filter((msg) => !queuedIds.has(msg.id))
        })
        break
      }

      case 'workflow_progress': {
        const status = String(d.status ?? '')
        set((draft) => {
          if (status === 'completed' || status === 'failed' || status === 'stopped') {
            // Keep the terminal state visible briefly is a UI concern; the
            // store clears successful terminal executions immediately.
            draft.activeWorkflowExecution =
              status === 'failed'
                ? {
                    executionId: String(d.execution_id ?? ''),
                    definitionName: String(d.definition_name ?? ''),
                    status,
                    nodeId: (d.node_id as string | null) ?? null,
                    nodeIndex: (d.node_index as number | null) ?? null,
                    totalNodes: Number(d.total_nodes) || 0,
                    error: (d.error as string | undefined) ?? null,
                  }
                : null
          } else {
            draft.activeWorkflowExecution = {
              executionId: String(d.execution_id ?? ''),
              definitionName: String(d.definition_name ?? ''),
              status,
              nodeId: (d.node_id as string | null) ?? null,
              nodeIndex: (d.node_index as number | null) ?? null,
              totalNodes: Number(d.total_nodes) || 0,
              error: null,
            }
          }
        })
        break
      }

      case 'goal_status': {
        set((draft) => {
          draft.activeGoal = (d.goal as GoalResponse | null | undefined) ?? null
        })
        break
      }

      case 'desktop_notification': {
        const kind = d.kind as string
        if (kind !== 'assistant_done' && kind !== 'background_done' && kind !== 'reminder_fired') break
        void sendDesktopNotification({
          kind,
          title: d.title as string,
          body: d.body as string,
        })
        break
      }

      case 'agent_status': {
        const agent = d.agent as string
        const status = d.status as string
        const meta = (d.metadata ?? {}) as Record<string, unknown>
        const phase = (meta.phase as string) ?? null
        set((draft) => {
          ensureAgent(draft, agent)
          if (status === 'working') {
            resetTurnUsage(draft.agentStreams[agent])
            draft.agentStreams[agent].status = 'working'
            draft.agentStreams[agent]._completionEstimated = 0
            if (phase === 'ingress' || phase === 'model_calling') {
              draft.agentStreams[agent].phase = phase as 'ingress' | 'model_calling'
            }
            draft.isTeamWorking = true
            if (draft.liveAgentNames && !draft.liveAgentNames.includes(agent)) draft.liveAgentNames.push(agent)
            draft.cacheInvalidations.push({ kind: 'team_sessions' })
            pushActivity(draft, { kind: 'spawn', agent, label: `${agent} started working` })
          } else if (status === 'idle') {
            draft.agentStreams[agent].status = 'idle'
            draft.agentStreams[agent].phase = null
            if (draft.liveAgentNames && !draft.liveAgentNames.includes(agent)) draft.liveAgentNames.push(agent)
          } else if (status === 'offline') {
            draft.agentStreams[agent].status = 'offline'
            draft.agentStreams[agent].phase = null
            if (draft.liveAgentNames) draft.liveAgentNames = draft.liveAgentNames.filter((name) => name !== agent)
            pushActivity(draft, { kind: 'dismiss', agent, label: `${agent} went offline` })
          } else if (status === 'error') {
            draft.agentStreams[agent].status = 'error'
            draft.agentStreams[agent].phase = null
            draft.agentStreams[agent].lastError =
              (d.metadata as Record<string, unknown>)?.message as string ?? null
            if (draft.liveAgentNames && !draft.liveAgentNames.includes(agent)) draft.liveAgentNames.push(agent)
            pushActivity(draft, { kind: 'status', agent, label: `${agent} encountered an error` })
          }
          if (status !== 'working') {
            draft.isTeamWorking = Object.values(draft.agentStreams).some(
              (s) => s.status === 'working',
            )
          }
        })
        break
      }

      case 'done': {
        set((draft) => {
          draft.isTeamWorking = false
          draft.isContinuing = false
          // Safety net: live question_replied / permission_replied /
          // plan_approval_replied normally dismiss gates; clear any leftover
          // if the turn ended without a matching replied event.
          draft.askUserQuestion = null
          draft.permissionRequest = null
          draft.planApproval = null
          const completedAtMs = Date.now()
          const completedAt = new Date(completedAtMs)
          Object.keys(draft.agentStreams).forEach((name) => {
            const stream = draft.agentStreams[name]
            if (stream.currentBlocks.length > 0) {
              const stamped = stampTurnUsage(
                stampOpenTextBlocks(stream.currentBlocks, completedAtMs, stream._turnStartedAt),
                stream.usage,
              ).map((b) => ({
                ...b,
                timestamp: b.timestamp ?? completedAt,
              }))
              stream.blocks = [...stream.blocks, ...stamped]
              stream.currentBlocks = []
            }
            stream._completionBase = stream.usage.completionTokens
            stream._completionEstimated = 0
            stream._turnCompletionEstimated = 0
            stream._turnStartedAt = null
            if (stream.status !== 'error' && stream.status !== 'offline') {
              stream.status = 'idle'
            }
          })
          draft.cacheInvalidations.push({ kind: 'team_sessions' })
          pushActivity(draft, { kind: 'done', agent: draft.leadName ?? 'team', label: 'Turn completed' })
        })
        break
      }

      case 'error': {
        set((draft) => {
          draft.error = d.message as string
          draft.isTeamWorking = false
          draft.isContinuing = false
          draft.askUserQuestion = null
          draft.permissionRequest = null
          draft.planApproval = null
        })
        break
      }

      case 'summarization_start': {
        const agent = d.agent as string
        if (!agent) break
        set((draft) => {
          ensureAgent(draft, agent)
          const stream = draft.agentStreams[agent]
          stream.blocks = startCompaction(stream.blocks)
        })
        break
      }

      case 'summarization_content': {
        // Compatibility with older backends that streamed summary deltas.
        // Compaction content is internal model context, not chat output.
        break
      }

      case 'summarization_end': {
        const agent = d.agent as string
        if (!agent) break
        const meta = d.metadata as Record<string, unknown> | undefined
        const error = Boolean(meta?.error)
        set((draft) => {
          ensureAgent(draft, agent)
          const stream = draft.agentStreams[agent]
          stream.blocks = endCompaction(stream.blocks, error)
        })
        break
      }

      case 'agent_not_configured': {
        const agent = d.agent as string
        set((draft) => {
          ensureAgent(draft, agent)
          draft.agentStreams[agent].status = 'error'
          draft.agentStreams[agent].lastError = d.message as string
          draft.setupRequired = {
            agent,
            message: d.message as string,
            action: (d.action as { type?: string; tab?: string } | undefined) ?? {},
          }
          draft.isTeamWorking = false
        })
        break
      }

      case 'browser_session': {
        const active = d.active as boolean
        const tabs = (d.tabs as Array<Record<string, unknown>> | undefined) ?? []
        set((draft) => {
          if (!active) {
            draft.browserSession = null
          } else {
            draft.browserSession = {
              active: true,
              cdpUrl: (d.cdp_url as string | undefined) ?? null,
              cdpHttp: (d.cdp_http as string | undefined) ?? null,
              currentUrl: (d.current_url as string | undefined) ?? null,
              currentTitle: (d.current_title as string | undefined) ?? null,
              tabs: tabs.map((t, i) => ({
                index: (t.index as number) ?? i,
                url: (t.url as string) ?? '',
                title: (t.title as string) ?? '',
              })),
              lastAction: (d.action as string | undefined) ?? null,
            }
          }
        })
        break
      }

      case 'permission_asked': {
        // The backend only emits this event when a tool call is actually
        // blocked awaiting a reply — mode handling lives server-side, so
        // every event received here should surface the approval UI.
        // Idempotent on reconnect replay of the same single-slot request.
        const requestId = d.request_id as string
        set((draft) => {
          if (draft.permissionRequest?.requestId === requestId) return
          draft.permissionRequest = {
            requestId,
            sessionId: d.session_id as string,
            tool: d.tool as string,
            patterns: (d.patterns as string[]) ?? [],
            metadata: (d.metadata as Record<string, unknown>) ?? {},
          }
        })
        break
      }

      case 'permission_replied': {
        // Includes interrupt cancel (reply: "reject") — dismiss, don't stick.
        set((draft) => {
          if (draft.permissionRequest?.requestId === (d.request_id as string)) {
            draft.permissionRequest = null
          }
        })
        break
      }

      case 'plan_approval_requested': {
        const requestId = d.request_id as string
        set((draft) => {
          // Same pending plan on reconnect replay — keep the review panel.
          if (draft.planApproval?.requestId === requestId) return
          draft.planApproval = {
            requestId,
            sessionId: d.session_id as string,
            plan: (d.plan as string) ?? '',
            steps: (d.steps as Array<Record<string, unknown>>).map((s) => ({
              tool: s.tool as string,
              args: (s.args as Record<string, unknown>) ?? {},
              summary: s.summary as string,
              path: typeof s.path === 'string' ? s.path : undefined,
              diff_stat:
                s.diff_stat && typeof s.diff_stat === 'object'
                  ? (s.diff_stat as { additions?: number | null; deletions?: number | null })
                  : undefined,
            })),
          }
        })
        break
      }

      case 'turn_changes': {
        const filesRaw = Array.isArray(d.files) ? d.files : []
        const files: TurnChangedFile[] = []
        for (const f of filesRaw) {
          if (!f || typeof f !== 'object') continue
          const row = f as Record<string, unknown>
          const path = typeof row.path === 'string' ? row.path : null
          if (!path) continue
          const statusRaw = row.status
          const status: TurnChangedFile['status'] =
            statusRaw === 'added' ||
            statusRaw === 'modified' ||
            statusRaw === 'removed' ||
            statusRaw === 'changed'
              ? statusRaw
              : 'changed'
          files.push({
            path,
            status,
            additions: typeof row.additions === 'number' ? row.additions : null,
            deletions: typeof row.deletions === 'number' ? row.deletions : null,
          })
        }
        set((draft) => {
          if (files.length === 0) {
            draft.turnChanges = null
            draft.turnChangesOpen = false
            return
          }
          draft.turnChanges = {
            sessionId: (d.session_id as string) ?? draft.sessionId ?? '',
            additions: typeof d.additions === 'number' ? d.additions : 0,
            deletions: typeof d.deletions === 'number' ? d.deletions : 0,
            files,
          }
          // Coding mode renders the completed-turn summary inline. Keep the
          // larger review panel closed until the user explicitly opens it.
          draft.turnChangesOpen = false
        })
        break
      }

      case 'plan_approval_replied': {
        // Another tab replied, or the request was cancelled by an
        // interrupt — close the plan-review UI everywhere.
        set((draft) => {
          if (draft.planApproval?.requestId === (d.request_id as string)) {
            draft.planApproval = null
          }
        })
        break
      }

      case 'question_asked': {
        const questionsRaw = Array.isArray(d.questions) ? d.questions : []
        const questions = questionsRaw
          .filter((q): q is Record<string, unknown> => !!q && typeof q === 'object')
          .map((q) => ({
            question: typeof q.question === 'string' ? q.question : '',
            options: Array.isArray(q.options)
              ? q.options.filter((opt): opt is string => typeof opt === 'string')
              : [],
            strict: q.strict === true,
            kind: q.kind === 'agent_spawn' ? 'agent_spawn' as const : 'text' as const,
            agentSpawn: q.kind === 'agent_spawn' && q.agent_spawn && typeof q.agent_spawn === 'object'
              ? {
                  blueprint: typeof (q.agent_spawn as Record<string, unknown>).blueprint === 'string'
                    ? (q.agent_spawn as Record<string, unknown>).blueprint as string
                    : '',
                  defaultModel: typeof (q.agent_spawn as Record<string, unknown>).default_model === 'string'
                    ? (q.agent_spawn as Record<string, unknown>).default_model as string
                    : '',
                  defaultThinkingLevel: typeof (q.agent_spawn as Record<string, unknown>).default_thinking_level === 'string'
                    ? (q.agent_spawn as Record<string, unknown>).default_thinking_level as string
                    : null,
                }
              : undefined,
          }))
          .filter((q) => q.question.length > 0)
        if (questions.length === 0) break
        const requestId = d.request_id as string
        set((draft) => {
          // Reconnect replay of the same batch — keep in-progress answers.
          if (draft.askUserQuestion?.requestId === requestId) return
          draft.askUserQuestion = {
            requestId,
            sessionId: d.session_id as string,
            questions,
          }
        })
        break
      }

      case 'question_replied': {
        // Reply or interrupt cancel — close the question UI everywhere.
        set((draft) => {
          if (draft.askUserQuestion?.requestId === (d.request_id as string)) {
            draft.askUserQuestion = null
          }
        })
        break
      }


    }
  }
}
