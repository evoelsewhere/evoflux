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
import { createNotificationActivation } from '@/lib/notification-activation'
import { useUIStore } from '@/stores/useUIStore'
import type { ContentBlock, GoalResponse, MotionProgressPayload, SuggestedTask, TurnCost, TurnUsage, TurnUsageBreakdown } from '@/api/types'
import type { UiBlockNode } from '@/components/ui/ui-block-types'
import { parseVisualArtifactMessage } from '@/lib/visual-artifact-bridge'
import { parseTurnChanges } from '@/utils/turn-changes'
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
    }
  }
  if (text) {
    stream._completionEstimated = (stream._completionEstimated ?? 0) + (text.length / 4)
    const newEstimatedVal = Math.round(stream._completionEstimated)
    const currentTurnTokens = Math.max(stream.usage.completionTokens - stream._completionBase, newEstimatedVal)
    stream.usage.completionTokens = stream._completionBase + currentTurnTokens
    // `totalTokens` = prompt + generated so far. The cumulative
    // `completionTokens` spans earlier turns and must not be folded in.
    stream.usage.totalTokens = stream.usage.promptTokens + currentTurnTokens

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

// ─── ui_block shared apply algorithm (§1.4/§1.6) ────────────────────────────
// One implementation feeds the live `ui_block` SSE event, the `tool_end`
// fallback, and — mirrored — history reconstruction in `@/utils/messages`, so
// replay and reload stay idempotent (§1.7). Identity = block_id ?? tool_call_id;
// a set replace_id matches the group carrying that identity instead. Hits
// update in place (identity/id/position immutable); misses append with
// identity = replace_id ?? block_id ?? tool_call_id.

type UiBlockScope = Pick<TeamStore['agentStreams'][string], 'blocks' | 'currentBlocks'>

interface UiBlockApplyCtx {
  toolCallId: string
  blockId?: string | null
  replaceId?: string | null
  blocks: UiBlockNode[]
  title?: string
  /** Append-only fallback title when the call supplies none (tool_end's legacy "UI Block"). */
  defaultTitle?: string
}

function uiBlockTarget(scope: UiBlockScope, ctx: UiBlockApplyCtx): ContentBlock | undefined {
  const key = ctx.replaceId ?? ctx.blockId ?? ctx.toolCallId
  // §1.5: a flush moves groups into stream.blocks — both count as scope.
  return [...scope.blocks, ...scope.currentBlocks].find(
    (b) => b.type === 'ui_block' && b.uiBlockIdentity === key,
  )
}

function applyUiBlock(scope: UiBlockScope, ctx: UiBlockApplyCtx): ContentBlock {
  const target = uiBlockTarget(scope, ctx)
  if (target) {
    // Hit — update in place; identity, id and position stay put, title only
    // when a later call supplies one.
    target.uiBlocks = ctx.blocks
    if (ctx.title) target.title = ctx.title
    target.toolCallId = ctx.toolCallId // latest writer
    return target
  }
  const title = ctx.title ?? ctx.defaultTitle
  const group: ContentBlock = {
    id: generateBlockId(),
    type: 'ui_block',
    content: '',
    uiBlocks: ctx.blocks,
    uiBlockIdentity: ctx.replaceId ?? ctx.blockId ?? ctx.toolCallId,
    toolCallId: ctx.toolCallId,
    isStreaming: false,
    ...(title ? { title } : {}),
  }
  scope.currentBlocks.push(group)
  return group
}

const MOTION_PHASES = ['planning', 'storyboard', 'style_samples', 'composing', 'rendering_samples', 'reviewing', 'revising', 'final_render', 'encoding', 'audio'] as const
const MOTION_STATUSES = ['running', 'complete', 'cancelled', 'failed', 'interrupted'] as const
const MOTION_SAMPLE_ROLES = ['style', 'key_state', 'before_transition', 'after_transition', 'impact'] as const

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function isBoundedId(value: unknown, max: number): value is string {
  return typeof value === 'string' && value.length <= max && /^[a-z0-9][a-z0-9_-]*$/.test(value)
}

function parseMotionProgress(raw: unknown): MotionProgressPayload | null {
  if (!isRecord(raw)) return null
  const value = raw
  if (
    typeof value.job_id !== 'string' || !/^motion-[a-f0-9]{32}$/.test(value.job_id)
    || !Number.isSafeInteger(value.sequence) || (value.sequence as number) < 1
    || !isBoundedId(value.artifact_id, 80)
    || !Number.isSafeInteger(value.artifact_revision) || (value.artifact_revision as number) < 1
    || !MOTION_STATUSES.includes(value.status as typeof MOTION_STATUSES[number])
    || !MOTION_PHASES.includes(value.phase as typeof MOTION_PHASES[number])
  ) return null

  let beat: MotionProgressPayload['beat']
  if (value.beat !== undefined && value.beat !== null) {
    if (!isRecord(value.beat)) return null
    const candidate = value.beat
    if (
      !isBoundedId(candidate.id, 64)
      || !Number.isSafeInteger(candidate.index) || (candidate.index as number) < 0
      || !Number.isSafeInteger(candidate.total) || (candidate.total as number) < 1 || (candidate.total as number) > 64
      || (candidate.index as number) >= (candidate.total as number)
      || typeof candidate.title !== 'string' || candidate.title.length < 1 || candidate.title.length > 120
    ) return null
    beat = { id: candidate.id, index: candidate.index as number, total: candidate.total as number, title: candidate.title }
  }

  let frames: MotionProgressPayload['frames']
  if (value.frames !== undefined && value.frames !== null) {
    if (!isRecord(value.frames)) return null
    const candidate = value.frames
    if (
      !['review_samples', 'final_output'].includes(String(candidate.scope))
      || !Number.isSafeInteger(candidate.completed) || (candidate.completed as number) < 0
      || !(candidate.total === null || candidate.total === undefined || (Number.isSafeInteger(candidate.total) && (candidate.total as number) >= 1))
      || (typeof candidate.total === 'number' && (candidate.completed as number) > candidate.total)
      || !(candidate.fps === null || candidate.fps === undefined || (typeof candidate.fps === 'number' && Number.isFinite(candidate.fps) && candidate.fps >= 1 && candidate.fps <= 240))
      || !(candidate.last_completed_index === null || candidate.last_completed_index === undefined || (Number.isSafeInteger(candidate.last_completed_index) && (candidate.last_completed_index as number) >= 0))
      || (typeof candidate.total === 'number' && typeof candidate.last_completed_index === 'number' && candidate.last_completed_index >= candidate.total)
      || ((candidate.completed as number) === 0 && typeof candidate.last_completed_index === 'number')
      || ((candidate.completed as number) > 0 && !Number.isSafeInteger(candidate.last_completed_index))
    ) return null
    frames = {
      scope: candidate.scope as 'review_samples' | 'final_output',
      completed: candidate.completed as number,
      total: typeof candidate.total === 'number' ? candidate.total : null,
      fps: typeof candidate.fps === 'number' ? candidate.fps : null,
      lastCompletedIndex: typeof candidate.last_completed_index === 'number' ? candidate.last_completed_index : null,
    }
  }

  let iteration: MotionProgressPayload['iteration']
  if (value.iteration !== undefined && value.iteration !== null) {
    if (!isRecord(value.iteration)) return null
    const current = value.iteration.current
    const budget = value.iteration.budget
    if (!Number.isSafeInteger(current) || (current as number) < 1 || !Number.isSafeInteger(budget) || (budget as number) < 1 || (budget as number) > 20 || (current as number) > (budget as number)) return null
    iteration = { current: current as number, budget: budget as number }
  }

  const rawSamples = value.selected_samples ?? []
  if (!Array.isArray(rawSamples) || rawSamples.length > 12) return null
  const selectedSamples: MotionProgressPayload['selectedSamples'] = []
  for (const rawSample of rawSamples) {
    if (!isRecord(rawSample)) return null
    if (
      !isBoundedId(rawSample.sample_id, 64) || !isBoundedId(rawSample.beat_id, 64)
      || !Number.isSafeInteger(rawSample.frame_index) || (rawSample.frame_index as number) < 0
      || !Number.isSafeInteger(rawSample.timestamp_ms) || (rawSample.timestamp_ms as number) < 0 || (rawSample.timestamp_ms as number) > 120_000
      || !MOTION_SAMPLE_ROLES.includes(rawSample.role as typeof MOTION_SAMPLE_ROLES[number])
    ) return null
    selectedSamples.push({
      sampleId: rawSample.sample_id,
      beatId: rawSample.beat_id,
      frameIndex: rawSample.frame_index as number,
      timestampMs: rawSample.timestamp_ms as number,
      role: rawSample.role as MotionProgressPayload['selectedSamples'][number]['role'],
    })
  }

  const audioStatus = value.audio_status ?? 'not_requested'
  if (!['not_requested', 'unavailable', 'pending', 'rendering', 'included'].includes(String(audioStatus))) return null
  const sampleRequestId = value.sample_request_id
  if (sampleRequestId !== undefined && (typeof sampleRequestId !== 'string' || sampleRequestId.length < 1 || sampleRequestId.length > 120 || selectedSamples.length === 0)) return null
  if (value.status === 'complete' && !['final_render', 'encoding', 'audio'].includes(String(value.phase))) return null

  return {
    jobId: value.job_id,
    sequence: value.sequence as number,
    artifactId: value.artifact_id,
    artifactRevision: value.artifact_revision as number,
    status: value.status as MotionProgressPayload['status'],
    phase: value.phase as MotionProgressPayload['phase'],
    ...(beat ? { beat } : {}),
    ...(frames ? { frames } : {}),
    ...(iteration ? { iteration } : {}),
    ...(typeof sampleRequestId === 'string' ? { sampleRequestId } : {}),
    selectedSamples,
    audioStatus: audioStatus as MotionProgressPayload['audioStatus'],
  }
}

function applyMotionProgress(scope: UiBlockScope, progress: MotionProgressPayload, toolCallId?: string): ContentBlock | undefined {
  const all = [...scope.blocks, ...scope.currentBlocks]
  const target = all.find((block) => block.motionProgress?.jobId === progress.jobId)
  const existing = target?.motionProgress
  if (existing && (progress.artifactRevision < existing.artifactRevision || progress.sequence <= existing.sequence)) return target
  if (target?.visualArtifact && progress.artifactRevision < target.visualArtifact.revision) return target
  if (target) {
    target.motionProgress = progress
    target.toolCallId = toolCallId ?? target.toolCallId
    target.title = target.visualArtifact?.title ?? progress.beat?.title ?? target.title ?? 'Motion explainer'
    target.isStreaming = progress.status === 'running'
    return target
  }
  const block: ContentBlock = {
    id: progress.jobId,
    type: 'motion_progress',
    content: '',
    title: progress.beat?.title ?? 'Motion explainer',
    ...(toolCallId ? { toolCallId } : {}),
    motionProgress: progress,
    isStreaming: progress.status === 'running',
  }
  scope.currentBlocks.push(block)
  return block
}

function applyVisualArtifact(
  scope: UiBlockScope,
  artifact: NonNullable<ContentBlock['visualArtifact']>,
  toolCallId: string,
  explicitRevision?: number,
): ContentBlock {
  const target = [...scope.currentBlocks].reverse().find(
    (block) => block.motionProgress?.artifactId === artifact.artifactId,
  ) ?? [...scope.blocks].reverse().find(
    (block) => block.motionProgress?.artifactId === artifact.artifactId,
  ) ?? [...scope.blocks, ...scope.currentBlocks].find(
    (block) => block.visualArtifact?.artifactId === artifact.artifactId,
  )
  if (target?.motionProgress && explicitRevision !== undefined && explicitRevision < target.motionProgress.artifactRevision) return target
  const revision = explicitRevision
    ?? target?.motionProgress?.artifactRevision
    ?? (target?.visualArtifact?.revision ? target.visualArtifact.revision + 1 : 1)
  if (target?.motionProgress && revision < target.motionProgress.artifactRevision) return target
  artifact.revision = revision
  if (target) {
    target.type = 'visual_artifact'
    target.visualArtifact = artifact
    target.title = artifact.title
    target.toolCallId = toolCallId
    return target
  }
  const block: ContentBlock = {
    id: artifact.artifactId,
    type: 'visual_artifact',
    content: '',
    title: artifact.title,
    toolCallId,
    visualArtifact: artifact,
    isStreaming: false,
  }
  scope.currentBlocks.push(block)
  return block
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

      case 'ui_block': {
        const agent = d.agent as string
        const toolCallId = d.tool_call_id as string
        const blocks = d.blocks
        if (!Array.isArray(blocks)) break
        const metadata = d.metadata as Record<string, unknown> | undefined
        const title = (d.title as string | undefined)
          ?? (metadata?.title as string | undefined)
        const blockId = typeof d.block_id === 'string' ? d.block_id : undefined
        const replaceId = typeof d.replace_id === 'string' ? d.replace_id : undefined
        set((draft) => {
          ensureAgent(draft, agent)
          // Shared apply (§1.4/§1.6): first arrival creates the group,
          // later same-identity/replace arrivals refresh it in place — over
          // stream.blocks too, so flushed replays never duplicate (§1.7).
          applyUiBlock(draft.agentStreams[agent], {
            toolCallId,
            blockId,
            replaceId,
            blocks: blocks as UiBlockNode[],
            title,
          })
        })
        break
      }

      case 'visual_artifact': {
        const agent = typeof d.agent === 'string' ? d.agent : ''
        const toolCallId = typeof d.tool_call_id === 'string' ? d.tool_call_id : ''
        const parsed = parseVisualArtifactMessage(d)
        if (!agent || !toolCallId || !parsed) break
        let acceptedArtifact: NonNullable<ContentBlock['visualArtifact']> | undefined
        set((draft) => {
          ensureAgent(draft, agent)
          const stream = draft.agentStreams[agent]
          const history = [...stream.blocks, ...stream.currentBlocks]
          parsed.sources = parsed.sources.map((source) => {
            const call = history.find((block) => block.type === 'tool' && block.toolCallId === source.toolCallId)
            if (!call?.toolDone || !call.toolResult || call.toolResult.trim().toLowerCase().startsWith('error:')) return source
            let verified = true
            try {
              const result: unknown = JSON.parse(call.toolResult)
              if (result && typeof result === 'object' && !Array.isArray(result)) {
                const data = result as Record<string, unknown>
                verified = data.success !== false && !data.error
              }
            } catch {
              // Plain-text successful tool results remain verifiable.
            }
            return verified ? {
              ...source,
              verified: true,
              toolName: call.toolName,
              arguments: call.toolArgs,
              result: call.toolResult,
            } : source
          })
          const explicitRevision = Number.isInteger(d.artifact_revision) && (d.artifact_revision as number) >= 1
            ? d.artifact_revision as number
            : undefined
          const merged = applyVisualArtifact(stream, parsed, toolCallId, explicitRevision)
          if (merged.visualArtifact === parsed) acceptedArtifact = parsed
        })
        if (!acceptedArtifact) break
        const ui = useUIStore.getState()
        const activeSessionId = get().sessionId
        if (activeSessionId && ui.workbenchSessionId === activeSessionId) {
          ui.openWorkbenchTool('visual-artifact', { title: acceptedArtifact.title, artifact: acceptedArtifact })
        }
        break
      }

      case 'motion_progress': {
        const agent = typeof d.agent === 'string' ? d.agent : ''
        const parsed = parseMotionProgress(d)
        if (!agent || !parsed) break
        set((draft) => {
          ensureAgent(draft, agent)
          applyMotionProgress(draft.agentStreams[agent], parsed)
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

            // Fallback: when show_widget's widget_delta events never arrived
            // (e.g. silent exception in the backend push), construct the widget
            // block from the tool-call arguments at tool_end time.
            if (toolName === 'show_widget' && toolCallId) {
              const blocks = draft.agentStreams[agent].currentBlocks
              const hasWidget = blocks.some(
                (b) => b.type === 'widget' && b.toolCallId === toolCallId,
              )
              if (!hasWidget) {
                const toolBlock = blocks.find(
                  (b) => b.type === 'tool' && b.toolCallId === toolCallId,
                )
                let parsedArgs: Record<string, unknown> | undefined
                try {
                  parsedArgs =
                    typeof toolBlock?.toolArgs === 'string'
                      ? JSON.parse(toolBlock.toolArgs)
                      : (toolBlock?.toolArgs as Record<string, unknown> | undefined)
                } catch {
                  // malformed args — skip
                }
                const widgetCode = parsedArgs?.widget_code as string | undefined
                if (widgetCode) {
                  blocks.push({
                    id: generateBlockId(),
                    type: 'widget',
                    content: '',
                    widgetHtml: widgetCode,
                    toolCallId,
                    isStreaming: false,
                    title: (parsedArgs?.title as string) || 'Widget',
                  })
                }
              }
            }

            // Fallback: when the ui_block event never arrived (e.g. backend
            // push failure), reconstruct the block from the persisted
            // tool-call arguments at tool_end time (Feature C, §6.2).
            // block_id/replace_id in the args run through the same
            // applyUiBlock as the event (§1.6), so a replace upserts the
            // existing group instead of appending a duplicate.
            if (toolName === 'ui_block' && toolCallId) {
              const stream = draft.agentStreams[agent]
              const hasUiBlock = [...stream.blocks, ...stream.currentBlocks].some(
                (b) => b.type === 'ui_block' && b.toolCallId === toolCallId,
              )
              if (!hasUiBlock) {
                const toolBlock = stream.currentBlocks.find(
                  (b) => b.type === 'tool' && b.toolCallId === toolCallId,
                )
                let parsedArgs: Record<string, unknown> | undefined
                try {
                  parsedArgs =
                    typeof toolBlock?.toolArgs === 'string'
                      ? JSON.parse(toolBlock.toolArgs)
                      : (toolBlock?.toolArgs as Record<string, unknown> | undefined)
                } catch {
                  // malformed args — skip
                }
                if (Array.isArray(parsedArgs?.blocks)) {
                  applyUiBlock(stream, {
                    toolCallId,
                    blockId:
                      typeof parsedArgs.block_id === 'string'
                        ? parsedArgs.block_id
                        : undefined,
                    replaceId:
                      typeof parsedArgs.replace_id === 'string'
                        ? parsedArgs.replace_id
                        : undefined,
                    blocks: parsedArgs.blocks as UiBlockNode[],
                    title:
                      typeof parsedArgs.title === 'string'
                        ? parsedArgs.title
                        : undefined,
                    defaultTitle: 'UI Block',
                  })
                }
              }
            }

            if (toolName === 'visual_artifact' && toolCallId) {
              const stream = draft.agentStreams[agent]
              const exists = [...stream.blocks, ...stream.currentBlocks].some(
                (block) => block.type === 'visual_artifact' && block.toolCallId === toolCallId,
              )
              if (!exists) {
                const toolBlock = stream.currentBlocks.find(
                  (block) => block.type === 'tool' && block.toolCallId === toolCallId,
                )
                try {
                  const rawArgs = typeof toolBlock?.toolArgs === 'string'
                    ? JSON.parse(toolBlock.toolArgs)
                    : toolBlock?.toolArgs
                  const parsed = parseVisualArtifactMessage({
                    ...(rawArgs as Record<string, unknown>),
                    type: 'visual_artifact',
                    agent,
                    tool_call_id: toolCallId,
                    is_final: true,
                  })
                  if (parsed) {
                    const explicitRevision = isRecord(rawArgs)
                      && Number.isInteger(rawArgs.artifact_revision)
                      && (rawArgs.artifact_revision as number) >= 1
                      ? rawArgs.artifact_revision as number
                      : undefined
                    applyVisualArtifact(stream, parsed, toolCallId, explicitRevision)
                  }
                } catch {
                  // Invalid or partial tool args are not rendered as artifacts.
                }
              }
            }
          })
        }
        if (isBackgroundCompletion(toolName, result)) {
          const state = get()
          const activation = state.sessionId
            ? createNotificationActivation('background_done', state.sessionId)
            : undefined
          void sendDesktopNotification({
            kind: 'background_done',
            title: `Background task completed${codingWorkspaceSuffix(state)}`,
            body: sessionLabel(state),
            ...(activation ? { activation } : {}),
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
            const projectId = get().projectId
            if (workspacePaths && workspacePaths.length > 0) {
              events.push({
                kind: 'coding_workspace_paths',
                workspace,
                paths: workspacePaths,
                projectId,
              })
            } else {
              events.push({ kind: 'coding_workspace', workspace, projectId })
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
          // `totalTokens` = the latest call's prompt plus its output — the
          // conversation's size as the model sees it. The cumulative
          // `u.completionTokens` covers every turn; folding it in here made
          // the number grow without bound as the session went on.
          u.totalTokens      = u.promptTokens + completionTokens
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
          // A steered message is already in the transcript — it was put
          // there when it was sent, rather than left in the tray. Its row id
          // is the block id, so the activation event must not add it twice.
          const rendered = new Set([
            ...stream.blocks.map((block) => block.id),
            ...stream.currentBlocks.map((block) => block.id),
          ])
          const fresh = messages.filter((msg) => !rendered.has(msg.id))
          if (fresh.length === 0) {
            draft._pendingMessages = draft._pendingMessages.filter(
              (msg) => !queuedIds.has(msg.id),
            )
            return
          }
          stream.currentBlocks = stampOpenTextBlocks(
            stream.currentBlocks,
            now,
            stream._turnStartedAt,
          )
          const nextTurnStartedAt = fresh[0]?.submittedAt ?? now
          stream.currentBlocks.push(
            ...fresh.map((msg) => ({
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

      case 'goal_status': {
        set((draft) => {
          draft.activeGoal = (d.goal as GoalResponse | null | undefined) ?? null
        })
        break
      }

      case 'suggested_task': {
        const task = d.task as SuggestedTask | undefined
        if (!task?.id) break
        set((draft) => {
          // The event carries the whole row, so an upsert keeps the dock
          // correct whether this is a new chip or one that just changed
          // state — and a task that left 'pending' simply leaves the list.
          const rest = draft.suggestedTasks.filter((t) => t.id !== task.id)
          draft.suggestedTasks = task.status === 'pending' ? [...rest, task] : rest
        })
        break
      }

      case 'next_message_suggestion': {
        const message = d.message as string | undefined
        if (typeof message === 'string' && message.trim().length > 0) {
          const reason = typeof d.reason === 'string' ? d.reason : ''
          set((draft) => {
            // The tool fires mid-turn, so this event lands before ``done``:
            // keep it pending and let ``done`` publish it. Last write wins
            // if the turn suggests more than once.
            draft._pendingNextMessageSuggestion = { message, reason }
          })
        }
        break
      }

      case 'desktop_notification': {
        const kind = d.kind as string
        if (kind !== 'assistant_done' && kind !== 'background_done' && kind !== 'reminder_fired') break
        const sessionId = get().sessionId ?? (d.session_id as string | undefined)
        const activation = sessionId ? createNotificationActivation(kind, sessionId) : undefined
        void sendDesktopNotification({
          kind,
          title: (d.title as string | undefined) ?? 'EvoFlux notification',
          body: (d.body as string | undefined) ?? '',
          ...(activation ? { activation } : {}),
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
            // ``agent_not_configured`` already explained this failure in the
            // agent's own terms. The status event carries the raw exception
            // text, which for a managed Agent points at the wrong fix — don't
            // let it overwrite the typed message.
            const statusMessage = (d.metadata as Record<string, unknown>)?.message as string ?? null
            if (draft.setupRequired?.agent !== agent) {
              draft.agentStreams[agent].lastError = statusMessage
            }
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
          // Promote the mid-turn suggestion, or clear a stale one when this
          // turn produced none, so only the finished turn's suggestion
          // survives the teardown below.
          draft.nextMessageSuggestion = draft._pendingNextMessageSuggestion
          draft._pendingNextMessageSuggestion = null
          draft.isTeamWorking = false
          draft.isContinuing = false
          // Safety net: live question_replied / permission_replied normally
          // dismiss gates; clear any leftover if the turn ended without a
          // matching replied event.
          draft.askUserQuestion = null
          draft.permissionRequest = null
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
          // An interrupted turn must not leave its suggestion to be promoted
          // by a later turn's ``done``.
          draft._pendingNextMessageSuggestion = null
          draft.isTeamWorking = false
          draft.isContinuing = false
          draft.askUserQuestion = null
          draft.permissionRequest = null
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
        const sessionId = get().sessionId ?? (d.session_id as string | undefined) ?? ''
        const activation = createNotificationActivation('agent_not_configured', sessionId)
        set((draft) => {
          ensureAgent(draft, agent)
          draft.agentStreams[agent].status = 'error'
          draft.agentStreams[agent].lastError = d.message as string
          draft.setupRequired = {
            agent,
            message: d.message as string,
            action: (d.action as { type?: string; tab?: string; agent?: string } | undefined) ?? {},
          }
          draft.isTeamWorking = false
        })
        void sendDesktopNotification({
          kind: 'agent_not_configured',
          title: 'Agent setup needed',
          body: (d.message as string | undefined) ?? `Configure ${agent} to continue.`,
          ...(activation ? { activation } : {}),
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
        const ownerSessionId = d.session_id as string
        const routeSessionId = get().sessionId ?? ownerSessionId
        const activation = createNotificationActivation('permission_asked', routeSessionId, requestId, [
          { id: 'permission-once', label: 'Allow once' },
          { id: 'permission-reject', label: 'Reject' },
        ])
        void sendDesktopNotification({
          kind: 'permission_asked',
          title: 'EvoFlux needs your approval',
          body: 'A tool is waiting for your permission.',
          ...(activation ? { activation } : {}),
        })
        set((draft) => {
          if (draft.permissionRequest?.requestId === requestId) return
          draft.permissionRequest = {
            requestId,
            sessionId: d.session_id as string,
            tool: d.tool as string,
            patterns: (d.patterns as string[]) ?? [],
            alwaysPatterns: (d.always_patterns as string[]) ?? [],
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

      case 'turn_changes': {
        set((draft) => {
          const changes = parseTurnChanges(draft.sessionId ?? '', d)
          if (!changes) {
            draft.turnChanges = null
            draft.turnChangesOpen = false
            return
          }
          draft.turnChanges = changes
          // Coding mode renders the completed-turn summary inline. Keep the
          // larger review panel closed until the user explicitly opens it.
          draft.turnChangesOpen = false
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
        const sessionId = d.session_id as string
        const onlyQuestion = questions.length === 1 ? questions[0] : undefined
        const actions = onlyQuestion?.kind === 'agent_spawn'
          && onlyQuestion.agentSpawn?.blueprint
          && onlyQuestion.agentSpawn.defaultModel.trim()
          ? [{ id: 'spawn-defaults', label: 'Spawn with defaults' }]
          : onlyQuestion?.kind !== 'agent_spawn'
            ? [
                ...(onlyQuestion?.options.slice(0, 2).map((option) => ({ id: 'choice', label: option, input: option })) ?? []),
                { id: 'answer', label: 'Reply' },
              ]
            : []
        const routeSessionId = get().sessionId ?? sessionId
        const activation = createNotificationActivation('question_asked', routeSessionId, requestId, actions)
        void sendDesktopNotification({
          kind: 'question_asked',
          title: onlyQuestion?.kind === 'agent_spawn' ? 'Agent spawn needs your input' : 'EvoFlux needs your input',
          body: onlyQuestion?.kind === 'agent_spawn'
            ? 'An agent is waiting to be configured.'
            : 'A question is waiting for your response.',
          ...(activation ? { activation } : {}),
        })
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
