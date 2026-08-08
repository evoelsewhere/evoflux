import type { ContentBlock } from '@/api/types'
import type { ActivityItem, AgentStream } from '@/stores/useTeamStore'

type DelegationToolState = 'start' | 'running' | 'success' | 'failed'

export type DelegationDisplayStatus =
  | 'queued'
  | 'running'
  | 'review'
  | 'done'
  | 'error'

export interface DelegationTarget {
  agent: string
  taskId?: string
}

export interface ParsedDelegationCall {
  targets: DelegationTarget[]
  title: string
  isolation?: 'shared' | 'worktree'
  repoCount?: number
}

export interface DelegationHandoffMatch {
  artifact: Record<string, unknown>
  receivedAt?: number
}

const UUID_PATTERN = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi

function stringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === 'string' && item.length > 0)
  }
  return typeof value === 'string' && value.length > 0 ? [value] : []
}

/** Parse both current structured calls and older single-recipient calls. */
export function parseDelegationCall(
  args: string | undefined,
  result: string | undefined,
): ParsedDelegationCall {
  let parsed: Record<string, unknown> = {}
  try {
    parsed = args ? (JSON.parse(args) as Record<string, unknown>) : {}
  } catch {
    // Keep the legacy fallback below.
  }

  const requested = [
    ...stringList(parsed.to),
    ...stringList(parsed.agent),
    ...stringList(parsed.member),
  ]
  const resolvedMatch = result?.match(/Task delegated to ([^.]+)\./i)
  const resolved = resolvedMatch?.[1]
    ?.split(',')
    .map((value) => value.trim())
    .filter(Boolean) ?? []
  const agents = resolved.length > 0 ? resolved : requested.length > 0 ? requested : ['agent']
  const taskIds = result?.match(UUID_PATTERN) ?? []
  const title =
    (typeof parsed.title === 'string' && parsed.title) ||
    (typeof parsed.task === 'string' && parsed.task) ||
    (typeof parsed.goal === 'string' && parsed.goal) ||
    (typeof parsed.content === 'string' && parsed.content) ||
    (typeof parsed.prompt === 'string' && parsed.prompt) ||
    'Delegated task'
  const requestedIsolation = parsed.isolation
  const isolation = requestedIsolation === 'shared' || requestedIsolation === 'worktree'
    ? requestedIsolation
    : undefined

  return {
    targets: agents.map((agent, index) => ({ agent, taskId: taskIds[index] })),
    title,
    isolation,
    repoCount: Array.isArray(parsed.target_repos) ? parsed.target_repos.length : undefined,
  }
}

function parseToolArgs(block: ContentBlock): Record<string, unknown> | null {
  if (block.type !== 'tool' || block.toolName !== 'team_handoff' || !block.toolArgs) return null
  try {
    return JSON.parse(block.toolArgs) as Record<string, unknown>
  } catch {
    return null
  }
}

function finalHandoffFromStream(stream: AgentStream | undefined, taskId?: string): boolean {
  if (!stream || !taskId) return false
  return [...stream.blocks, ...stream.currentBlocks].some((block) => {
    if (!block.toolDone || block.toolResult?.trimStart().toLowerCase().startsWith('error:')) {
      return false
    }
    const parsed = parseToolArgs(block)
    if (!parsed || parsed.task_id !== taskId) return false
    return parsed.status === undefined || parsed.status === 'final'
  })
}

export function delegationHandoffMatch(
  activityLog: ActivityItem[],
  stream: AgentStream | undefined,
  taskId?: string,
  inboxBlocks: ContentBlock[] = [],
): DelegationHandoffMatch | null {
  if (taskId) {
    const activity = [...activityLog].reverse().find((item) =>
      item.kind === 'handoff' && item.artifact?.task_id === taskId,
    )
    if (activity?.artifact) {
      return { artifact: activity.artifact, receivedAt: activity.timestamp.getTime() }
    }

    const inboxBlock = [...inboxBlocks].reverse().find((block) =>
      block.type === 'user' && block.extra?._handoff_artifact
      && (block.extra._handoff_artifact as Record<string, unknown>).task_id === taskId,
    )
    if (inboxBlock?.extra?._handoff_artifact) {
      return {
        artifact: inboxBlock.extra._handoff_artifact as Record<string, unknown>,
        receivedAt: inboxBlock.timestamp?.getTime(),
      }
    }
  }
  return finalHandoffFromStream(stream, taskId)
    ? { artifact: { task_id: taskId, status: 'final' } }
    : null
}

export function delegationHandoff(
  activityLog: ActivityItem[],
  stream: AgentStream | undefined,
  taskId?: string,
  inboxBlocks: ContentBlock[] = [],
): Record<string, unknown> | null {
  return delegationHandoffMatch(activityLog, stream, taskId, inboxBlocks)?.artifact ?? null
}

export function delegationDisplayStatus({
  toolState,
  stream,
  handoff,
}: {
  toolState: DelegationToolState
  stream: AgentStream | undefined
  handoff: Record<string, unknown> | null
}): DelegationDisplayStatus {
  if (toolState === 'failed') return 'error'
  if (handoff?.status === 'final') {
    return handoff.workspace_result ? 'review' : 'done'
  }
  if (handoff?.status === 'partial') return 'running'
  if (stream?.status === 'error') return 'error'
  if (stream?.status === 'working') return 'running'
  return 'queued'
}

function compactText(value: string, max = 68): string {
  const normalized = value.replace(/\s+/g, ' ').trim()
  return normalized.length > max ? `${normalized.slice(0, max - 1)}…` : normalized
}

export function delegationActivityLabel(
  status: DelegationDisplayStatus,
  stream: AgentStream | undefined,
  handoff: Record<string, unknown> | null,
): string {
  if (status === 'error') return stream?.lastError || 'Subagent encountered an error'
  if (status === 'review') return 'Final handoff received · changes ready for review'
  if (status === 'done') {
    return typeof handoff?.summary === 'string' ? compactText(handoff.summary) : 'Final handoff received'
  }
  if (status === 'queued') {
    return stream?.status === 'offline' ? 'Waiting for subagent to come online…' : 'Waiting for subagent to start…'
  }
  if (handoff?.status === 'partial' && typeof handoff.summary === 'string') {
    return `Partial handoff · ${compactText(handoff.summary, 52)}`
  }

  const blocks = stream?.currentBlocks ?? []
  const activeTool = [...blocks].reverse().find((block) => block.type === 'tool' && !block.toolDone)
  if (activeTool?.toolName) {
    const args = activeTool.toolArgs
    if (!args) return `Running ${activeTool.toolName}`
    try {
      const parsed = JSON.parse(args) as Record<string, unknown>
      const detail = Object.values(parsed).find((value): value is string => typeof value === 'string')
      return detail
        ? `${activeTool.toolName} · ${compactText(detail, 48)}`
        : `Running ${activeTool.toolName}`
    } catch {
      return `Running ${activeTool.toolName}`
    }
  }
  if (blocks.some((block) => block.type === 'thinking')) return 'Thinking…'
  if (blocks.some((block) => block.type === 'text')) return 'Preparing the handoff…'
  return 'Subagent is working…'
}
