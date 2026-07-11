import {
  appendThinking,
  appendText,
  initTool,
  addTool,
  appendToolOutput,
  completeTool,
  generateBlockId,
  startCompaction,
  appendCompactionContent,
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

function markTurnStarted(draft: TeamStore, agent: string, startedAt = Date.now()) {
  ensureAgent(draft, agent)
  const stream = draft.agentStreams[agent]
  if (stream._turnStartedAt === undefined || stream._turnStartedAt === null) stream._turnStartedAt = startedAt
}

function appendStreamingText(
  draft: TeamStore,
  agent: string,
  kind: BufferedTextKind,
  text: string,
  model?: string | null,
) {
  ensureAgent(draft, agent)
  const stream = draft.agentStreams[agent]
  if (stream._turnStartedAt === undefined || stream._turnStartedAt === null) stream._turnStartedAt = Date.now()
  if (kind === 'thinking') {
    stream.currentBlocks = appendThinking(stream.currentBlocks, text)
  } else {
    stream.currentBlocks = appendText(stream.currentBlocks, text)
    const last = stream.currentBlocks[stream.currentBlocks.length - 1]
    if (last?.type === 'text') {
      if (!last.startedAt) last.startedAt = Date.now()
      if (model) last.extra = { ...(last.extra ?? {}), model }
    }
  }
  if (text) {
    stream._completionEstimated = (stream._completionEstimated ?? 0) + (text.length / 4)
    const newEstimatedVal = Math.round(stream._completionEstimated)
    const currentTurnTokens = Math.max(stream.usage.completionTokens - stream._completionBase, newEstimatedVal)
    stream.usage.completionTokens = stream._completionBase + currentTurnTokens
    stream.usage.totalTokens = stream.usage.promptTokens + stream.usage.completionTokens
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

      case 'chapter_created': {
        const sessionId = d.session_id as string | undefined
        if (sessionId) {
          set((draft) => {
            draft.cacheInvalidations = [
              ...draft.cacheInvalidations,
              { kind: 'chapters', sessionId },
            ]
          })
        }
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
          appendStreamingText(draft, agent, 'message', text, typeof meta?.model === 'string' ? meta.model : null)
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
              mcpApp ? { mcp_app: mcpApp } : undefined,
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
          if (meta?.turn_total) {
            u.turnPromptTokens = promptTokens
            u.turnCompletionTokens = completionTokens
            u.turnTotalTokens = (d.total_tokens as number) || (promptTokens + completionTokens)
            u.turnCachedTokens = cachedTokens ?? 0
            return
          }
          u.promptTokens     = promptTokens
          u.completionTokens = stream._completionBase + completionTokens
          u.cachedTokens     = cachedTokens ?? u.cachedTokens
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

      case 'loop_status': {
        const limit = Number(d.limit) || 0
        const remaining = Number(d.remaining) || 0
        const prompt = typeof d.prompt === 'string' && d.prompt ? d.prompt : null
        const used = Number(d.used) || Math.max(limit - remaining, 0)
        const paused = Boolean(d.paused)
        set((draft) => {
          if (prompt || limit > 0) {
            draft.activeLoop = {
              prompt,
              limit,
              remaining,
              used,
              paused,
              // Loop Engine v2 fields — map snake_case server data to camelCase
              ...(d.current_iteration !== undefined ? { currentIteration: Number(d.current_iteration) } : {}),
              ...(d.total_tokens_used !== undefined ? { totalTokensUsed: Number(d.total_tokens_used) } : {}),
              ...(d.goal !== undefined ? { goal: d.goal as string | null } : {}),
              ...(d.goal_met !== undefined ? { goalMet: Boolean(d.goal_met) } : {}),
              ...(d.consecutive_errors !== undefined ? { consecutiveErrors: Number(d.consecutive_errors) } : {}),
              ...(d.no_progress_warning !== undefined ? { noProgressWarning: Boolean(d.no_progress_warning) } : {}),
              ...(Array.isArray(d.turn_history) ? { turnHistory: d.turn_history.map((t: Record<string, unknown>) => ({
                iteration: Number(t.iteration) || 0,
                success: t.success as boolean | null,
                tokensUsed: Number(t.tokens_used) || 0,
                durationMs: t.duration_ms != null ? Number(t.duration_ms) : null,
                error: (t.error as string) ?? null,
                errorCategory: (t.error_category as string) ?? null,
              })) } : {}),
              ...(d.config && typeof d.config === 'object' ? { config: d.config as import('./types').LoopConfigSummary } : {}),
            }
          } else {
            draft.activeLoop = null
          }
        })
        break
      }

      case 'loop_turn_complete': {
        // Individual turn result — already reflected in next loop_status,
        // but available for toast/notification consumers.
        break
      }

      case 'loop_stopped': {
        // Loop terminated — already clears activeLoop via the final
        // loop_status event, but available for notification consumers.
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
        set((draft) => {
          ensureAgent(draft, agent)
          if (status === 'working') {
            draft.agentStreams[agent].status = 'working'
            draft.agentStreams[agent]._completionEstimated = 0
            draft.isTeamWorking = true
            if (draft.liveAgentNames && !draft.liveAgentNames.includes(agent)) draft.liveAgentNames.push(agent)
            draft.cacheInvalidations.push({ kind: 'team_sessions' })
            pushActivity(draft, { kind: 'spawn', agent, label: `${agent} started working` })
          } else if (status === 'idle') {
            draft.agentStreams[agent].status = 'idle'
            if (draft.liveAgentNames && !draft.liveAgentNames.includes(agent)) draft.liveAgentNames.push(agent)
          } else if (status === 'offline') {
            draft.agentStreams[agent].status = 'offline'
            if (draft.liveAgentNames) draft.liveAgentNames = draft.liveAgentNames.filter((name) => name !== agent)
            pushActivity(draft, { kind: 'dismiss', agent, label: `${agent} went offline` })
          } else if (status === 'error') {
            draft.agentStreams[agent].status = 'error'
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
          const completedAtMs = Date.now()
          const completedAt = new Date(completedAtMs)
          Object.keys(draft.agentStreams).forEach((name) => {
            const stream = draft.agentStreams[name]
            if (stream.currentBlocks.length > 0) {
              const stamped = stampOpenTextBlocks(stream.currentBlocks, completedAtMs, stream._turnStartedAt).map((b) => ({
                ...b,
                timestamp: b.timestamp ?? completedAt,
              }))
              stream.blocks = [...stream.blocks, ...stamped]
              stream.currentBlocks = []
            }
            stream._completionBase = stream.usage.completionTokens
            stream._completionEstimated = 0
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
        const agent = d.agent as string
        const text = d.text as string
        if (!agent || !text) break
        set((draft) => {
          ensureAgent(draft, agent)
          const stream = draft.agentStreams[agent]
          stream.blocks = appendCompactionContent(stream.blocks, text)
        })
        break
      }

      case 'summarization_end': {
        const agent = d.agent as string
        if (!agent) break
        const summary = (d.summary as string | undefined) ?? ''
        const meta = d.metadata as Record<string, unknown> | undefined
        const error = Boolean(meta?.error)
        set((draft) => {
          ensureAgent(draft, agent)
          const stream = draft.agentStreams[agent]
          stream.blocks = endCompaction(stream.blocks, summary, error)
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
        set((draft) => {
          draft.permissionRequest = {
            requestId: d.request_id as string,
            sessionId: d.session_id as string,
            tool: d.tool as string,
            patterns: (d.patterns as string[]) ?? [],
            metadata: (d.metadata as Record<string, unknown>) ?? {},
          }
        })
        break
      }

      case 'permission_replied': {
        set((draft) => {
          if (draft.permissionRequest?.requestId === (d.request_id as string)) {
            draft.permissionRequest = null
          }
        })
        break
      }

      case 'plan_approval_requested': {
        set((draft) => {
          draft.planApproval = {
            requestId: d.request_id as string,
            sessionId: d.session_id as string,
            steps: (d.steps as Array<Record<string, unknown>>).map((s) => ({
              tool: s.tool as string,
              args: (s.args as Record<string, unknown>) ?? {},
              summary: s.summary as string,
            })),
          }
        })
        break
      }

      case 'question_asked': {
        set((draft) => {
          draft.askUserQuestion = {
            requestId: d.request_id as string,
            sessionId: d.session_id as string,
            questions: (d.questions as Array<Record<string, unknown>>).map((q) => ({
              question: q.question as string,
              options: (q.options as string[]) ?? [],
            })),
          }
        })
        break
      }

      case 'prompt_suggestions': {
        const suggestions = Array.isArray(d.suggestions)
          ? (d.suggestions as string[]).filter((s) => typeof s === 'string' && s.trim())
          : []
        if (suggestions.length > 0) {
          set((draft) => { draft.promptSuggestions = suggestions })
        }
        break
      }
    }
  }
}
