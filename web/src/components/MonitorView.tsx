/**
 * MonitorView — mission-control overview for multi-agent sessions.
 *
 * Two sections:
 *   1. Agent status strip — horizontally scrollable row of fixed-width cards,
 *      one per live agent. Shows current tool, proportional token bar, and
 *      role-colored status dot.
 *   2. Comms feed — inter-agent messages (inbox/handoff) plus lifecycle events
 *      (spawn/dismiss/done/status) in chronological order with relative timestamps.
 */

import { useEffect, useMemo, useRef } from 'react'
import { motion } from 'framer-motion'
import { fadeRise, useListEnterIndex, useMotionPreset } from '@/lib/motion'
import { ListEnter } from '@/components/motion/ListEnter'
import {
  ArrowRight,
  CheckCircle2,
  LogIn,
  LogOut,
  AlertTriangle,
  Radio,
} from 'lucide-react'
import { useTeamStore } from '@/stores/useTeamStore'
import type { ActivityItem } from '@/stores/useTeamStore'
import { resolveAgentRole } from '@/lib/agent-roles'
import { cn } from '@/lib/utils'
import { ScrollArea } from '@/components/ui/scroll-area'
import { AgentChip } from '@/components/ui/agent-chip'
import { AgentLogo } from '@/components/AgentLogo'
import { SubagentTaskCard } from '@/components/SubagentTaskCard'
import type { AgentStream } from '@/stores/useTeamStore'
import type { ContentBlock } from '@/api/types'
import { getIntlLocale } from '@/i18n'

// ── Utilities ─────────────────────────────────────────────────────────────────

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

/** Relative time computed at render — stays accurate via natural store re-renders. */
function relativeTime(date: Date): string {
  const diffSec = Math.floor((Date.now() - date.getTime()) / 1000)
  if (diffSec < 5) return 'just now'
  if (diffSec < 60) return `${diffSec}s ago`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  return date.toLocaleTimeString(getIntlLocale(), { hour: '2-digit', minute: '2-digit' })
}

function dotClass(stream: AgentStream): string {
  if (stream.status === 'error') return 'bg-(--color-error)'
  if (stream.status === 'offline') return 'bg-(--color-text-subtle) opacity-40'
  if (stream.status === 'working') return 'animate-pulse bg-(--color-accent)'
  return 'bg-(--color-success)'
}

function activeTool(blocks: ContentBlock[]): { name: string; args?: string } | null {
  for (let i = blocks.length - 1; i >= 0; i--) {
    const b = blocks[i]
    if (b.type === 'tool' && !b.toolDone) {
      return { name: b.toolName ?? 'tool', args: b.toolArgs }
    }
  }
  return null
}

function truncateArg(args: string | undefined): string {
  if (!args) return ''
  try {
    const parsed = JSON.parse(args)
    const first = Object.values(parsed)[0]
    if (typeof first === 'string') {
      const s = first.trim().replace(/\n/g, ' ')
      return s.length > 48 ? `${s.slice(0, 45)}…` : s
    }
  } catch { /* not JSON */ }
  return args.length > 48 ? `${args.slice(0, 45)}…` : args
}

// ── Agent status card ──────────────────────────────────────────────────────────

function AgentStatusCard({
  name,
  stream,
  isLead,
  maxTokens,
  onFocus,
}: {
  name: string
  stream: AgentStream
  isLead: boolean
  maxTokens: number
  onFocus?: (name: string) => void
}) {
  const total = stream.usage.totalTokens ?? 0
  const hasTokens = total > 0
  const fillPct = hasTokens && maxTokens > 1 ? Math.min(100, (total / maxTokens) * 100) : 0
  const tool = stream.status === 'working' ? activeTool(stream.currentBlocks) : null
  const isError = stream.status === 'error'
  const isWorking = stream.status === 'working'
  const interactive = Boolean(onFocus)

  return (
    <button
      type="button"
      onClick={() => onFocus?.(name)}
      disabled={!interactive}
      className={cn(
        'flex w-44 shrink-0 flex-col gap-2.5 rounded-lg border p-3 text-left transition-colors',
        interactive && 'cursor-pointer hover:border-(--color-border-strong) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)',
        !interactive && 'cursor-default',
        isError
          ? 'border-(--color-error)/35 bg-(--color-error)/5'
          : isWorking
          ? 'border-(--color-accent)/30 bg-(--bg-card)'
          : 'border-(--color-border) bg-(--bg-card)',
      )}
      aria-label={interactive ? `Focus agent ${name}` : `Agent ${name}, ${stream.status}`}
      aria-disabled={!interactive}
    >
      {/* Name + lead badge */}
      <div className="flex items-center gap-2">
        <AgentChip
          role={resolveAgentRole(name)}
          label={name}
          active={isLead || isWorking}
          className="min-w-0 flex-1 truncate px-2 py-1"
          dotClassName={dotClass(stream)}
        />
        {isLead && (
          <span className="shrink-0 rounded bg-(--bg-key) px-1.5 py-0.5 font-mono text-[10px] text-(--color-text-muted)">
            lead
          </span>
        )}
      </div>

      {/* Current tool / status text */}
      <div className="min-h-[18px]">
        {tool?.name === 'team_delegate' ? (
          <SubagentTaskCard
            agent={(() => {
              try {
                const parsed = tool.args ? JSON.parse(tool.args) as Record<string, unknown> : {}
                const to =
                  (typeof parsed.to === 'string' && parsed.to) ||
                  (typeof parsed.agent === 'string' && parsed.agent) ||
                  (typeof parsed.member === 'string' && parsed.member) ||
                  'agent'
                return to
              } catch {
                return 'agent'
              }
            })()}
            title={truncateArg(tool.args) || 'Delegated task'}
            status={isWorking ? 'running' : 'idle'}
            interactive={false}
            className="border-0 bg-transparent p-0"
          />
        ) : tool ? (
          <div className="flex items-start gap-1.5 overflow-hidden">
            <span className="mt-px shrink-0 font-mono text-[10px] text-(--color-accent) opacity-70">▶</span>
            <span className="min-w-0 break-all font-mono text-[10px] leading-tight text-(--color-text-muted)">
              {tool.name}
              {tool.args && (
                <span className="text-(--color-text-subtle)"> {truncateArg(tool.args)}</span>
              )}
            </span>
          </div>
        ) : (
          <span className="text-[11px] italic text-(--color-text-subtle)">
            {isError
              ? (stream.lastError?.slice(0, 60) ?? 'error')
              : stream.status === 'offline'
              ? 'offline'
              : 'idle'}
          </span>
        )}
      </div>

      {/* Token bar — only shown once agent has used tokens */}
      <div className="flex items-center gap-2">
        <div className="h-[3px] flex-1 overflow-hidden rounded-full bg-(--bg-key)">
          {hasTokens && (
            <div
              className={cn(
                'h-full rounded-full transition-[width] duration-(--motion-base)',
                isError ? 'bg-(--color-error)' : 'bg-(--color-accent)',
              )}
              style={{ width: `${fillPct}%` }}
            />
          )}
        </div>
        <span className="w-8 shrink-0 text-right font-mono text-[10px] tabular-nums text-(--color-text-subtle)">
          {hasTokens ? formatTokens(total) : '—'}
        </span>
      </div>
    </button>
  )
}

// ── Comms feed rows ────────────────────────────────────────────────────────────

function LifecycleRow({ item }: { item: ActivityItem }) {
  const isDone = item.kind === 'done'
  const isSpawn = item.kind === 'spawn'
  const isStatus = item.kind === 'status'

  return (
    <div className="flex items-center gap-2 px-4 py-1.5 text-xs text-(--color-text-subtle)">
      <AgentLogo name={item.agent} size="xs" />
      {isSpawn && <LogIn size={11} className="shrink-0 text-(--color-success)" aria-hidden="true" />}
      {item.kind === 'dismiss' && <LogOut size={11} className="shrink-0" aria-hidden="true" />}
      {isDone && <CheckCircle2 size={11} className="shrink-0 text-(--color-success)" aria-hidden="true" />}
      {isStatus && <AlertTriangle size={11} className="shrink-0 text-amber-500" aria-hidden="true" />}
      <span className="font-mono text-[11px] text-(--color-text-muted)">{item.agent}</span>
      <span>
        {isSpawn ? 'joined' : item.kind === 'dismiss' ? 'left' : isDone ? 'turn done' : item.label}
      </span>
      <span
        className="ml-auto shrink-0 font-mono text-[10px]"
        title={item.timestamp.toLocaleTimeString(getIntlLocale())}
      >
        {relativeTime(item.timestamp)}
      </span>
    </div>
  )
}

function CommsRow({ item }: { item: ActivityItem }) {
  if (item.kind === 'delegation') {
    const toAgents = Array.isArray(item.meta?.to_agents)
      ? (item.meta.to_agents as string[])
      : []
    const title = typeof item.meta?.title === 'string' ? item.meta.title : item.label
    const spec = item.meta?.spec && typeof item.meta.spec === 'object'
      ? (item.meta.spec as Record<string, unknown>)
      : undefined
    const resolvedIsolation = spec?.resolved_isolation === 'worktree'
      || spec?.isolation === 'worktree'
      ? 'worktree'
      : spec?.resolved_isolation === 'shared' || spec?.isolation === 'shared'
        ? 'shared'
        : undefined
    const repoCount = Array.isArray(spec?.target_repos) ? spec.target_repos.length : undefined
    return (
      <div className="px-3 py-1.5">
        <SubagentTaskCard
          agent={toAgents[0] ?? item.agent}
          title={title}
          status="running"
          isolation={resolvedIsolation}
          repoCount={repoCount}
          interactive={false}
        />
      </div>
    )
  }
  if (item.kind !== 'inbox' && item.kind !== 'handoff') {
    return <LifecycleRow item={item} />
  }

  const isHandoff = item.kind === 'handoff'
  const fromAgent = (item.meta?.from_agent as string | undefined) ?? item.agent
  const toAgents: string[] = isHandoff
    ? ((item.meta?.to_agents as string[] | undefined) ?? [item.agent])
    : [item.agent]

  const body = typeof item.artifact?.summary === 'string'
    ? item.artifact.summary
    : item.label
        .replace(/^(Message|Handoff)\s+(from|to)\s+[\w-]+\s*(→\s*[\w-]+)?\s*:?\s*/i, '')
        .trim()

  return (
    <div
      className={cn(
        'grid items-baseline gap-x-2 px-4 py-2.5 hover:bg-(--bg-key)',
        isHandoff && 'border-l-2 border-(--color-accent)/35',
      )}
      style={{ gridTemplateColumns: 'auto auto auto 1fr auto' }}
    >
      <span className="flex min-w-0 items-center gap-1.5 font-mono text-[11px] font-semibold text-(--color-text)">
        <AgentLogo name={fromAgent} size="xs" />
        <span className="truncate">{fromAgent}</span>
      </span>
      <ArrowRight size={11} className="text-(--color-text-subtle)" aria-hidden="true" />
      <span className="flex min-w-0 items-center gap-1.5 font-mono text-[11px] font-semibold text-(--color-accent)">
        <AgentLogo name={toAgents[0] ?? 'agent'} size="xs" />
        <span className="truncate">{toAgents.join(', ')}</span>
      </span>
      <span
        className="min-w-0 truncate text-xs leading-relaxed text-(--color-text-muted)"
        title={body || item.label}
      >
        {body || item.label}
      </span>
      <span
        className="font-mono text-[10px] text-(--color-text-subtle)"
        title={item.timestamp.toLocaleTimeString(getIntlLocale())}
      >
        {relativeTime(item.timestamp)}
      </span>
    </div>
  )
}

// ── Empty state ────────────────────────────────────────────────────────────────

function FeedEmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-(--bg-key)">
        <Radio size={18} className="text-(--color-text-subtle)" aria-hidden="true" />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium text-(--color-text-muted)">Listening for activity</p>
        <p className="text-xs text-(--color-text-subtle)">
          Inter-agent messages and handoffs will appear here.
        </p>
      </div>
    </div>
  )
}

// ── MonitorView ────────────────────────────────────────────────────────────────

export function MonitorView({
  agentNames,
  leadName,
  agentStreams,
  onFocusAgent,
}: {
  agentNames: string[]
  leadName: string | null
  agentStreams: Record<string, AgentStream>
  /** Focus an agent and leave monitor (caller switches view mode). */
  onFocusAgent?: (name: string) => void
}) {
  const activityLog = useTeamStore((s) => s.activityLog)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [activityLog.length])

  const liveAgents = useMemo(
    () => agentNames.filter((n) => agentStreams[n]?.status !== 'offline'),
    [agentNames, agentStreams],
  )

  const maxTokens = useMemo(
    () => Math.max(1, ...liveAgents.map((n) => agentStreams[n]?.usage.totalTokens ?? 0)),
    [liveAgents, agentStreams],
  )

  const feedItems = useMemo(
    () =>
      activityLog.filter(
        (i) =>
          i.kind === 'inbox' ||
          i.kind === 'handoff' ||
          i.kind === 'delegation' ||
          i.kind === 'done' ||
          i.kind === 'spawn' ||
          i.kind === 'dismiss' ||
          i.kind === 'status',
      ),
    [activityLog],
  )

  const workingCount = useMemo(
    () => liveAgents.filter((n) => agentStreams[n]?.status === 'working').length,
    [liveAgents, agentStreams],
  )

  const preset = useMotionPreset()
  const sectionEnter = fadeRise(preset, 6)
  const agentEnterIndex = useListEnterIndex(liveAgents, 12)
  const feedIds = useMemo(() => feedItems.map((item) => item.id), [feedItems])
  const feedEnterIndex = useListEnterIndex(feedIds, 12)

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Agent status strip */}
      <motion.div
        className="shrink-0 border-b border-(--color-border) bg-(--bg-page)"
        {...sectionEnter}
      >
        {liveAgents.length === 0 ? (
          <p className="px-4 py-3 text-xs text-(--color-text-subtle)">No active agents</p>
        ) : (
          <>
            {/* Summary line */}
            <div className="flex items-center gap-2 px-3 pb-1.5 pt-2.5">
              <span className="text-[11px] text-(--color-text-subtle)">
                {liveAgents.length} agent{liveAgents.length !== 1 ? 's' : ''}
              </span>
              {workingCount > 0 && (
                <>
                  <span className="text-(--color-border)">·</span>
                  <span className="flex items-center gap-1 text-[11px] text-(--color-accent)">
                    <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-(--color-accent)" />
                    {workingCount} working
                  </span>
                </>
              )}
            </div>
            {/* Horizontally scrollable card row — hides scrollbar for clean look */}
            <div className="flex gap-2 overflow-x-auto px-3 pb-3 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
              {liveAgents.map((name) => {
                const idx = agentEnterIndex(name)
                return (
                  <ListEnter
                    key={name}
                    index={idx ?? 0}
                    basePx={4}
                    className="shrink-0"
                    disabled={idx === undefined}
                  >
                    <AgentStatusCard
                      name={name}
                      stream={agentStreams[name]}
                      isLead={name === leadName}
                      maxTokens={maxTokens}
                      onFocus={onFocusAgent}
                    />
                  </ListEnter>
                )
              })}
            </div>
          </>
        )}
      </motion.div>

      {/* Comms feed */}
      <motion.div
        className="min-h-0 flex-1 bg-(--bg-page)"
        {...sectionEnter}
        transition={{ ...sectionEnter.transition, delay: preset.stagger * 2 }}
      >
        {feedItems.length === 0 ? (
          <FeedEmptyState />
        ) : (
          <ScrollArea className="h-full">
            <div className="divide-y divide-(--color-border)/40 py-1">
              {feedItems.map((item) => {
                const idx = feedEnterIndex(item.id)
                if (idx === undefined) {
                  return <CommsRow key={item.id} item={item} />
                }
                return (
                  <ListEnter key={item.id} index={idx} basePx={4}>
                    <CommsRow item={item} />
                  </ListEnter>
                )
              })}
              <div ref={bottomRef} />
            </div>
          </ScrollArea>
        )}
      </motion.div>
    </div>
  )
}
