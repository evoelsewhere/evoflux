/**
 * SplitWorkbench — focused multi-agent workspace.
 *
 * Split mode deliberately renders only one full transcript at a time. A
 * lightweight team rail keeps every agent visible without mounting a grid of
 * Markdown-heavy conversations. Users can add one secondary agent for a
 * resizable two-pane comparison.
 */
import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Columns2,
  PanelRightClose,
  PanelRightOpen,
  Wrench,
  X,
} from 'lucide-react'
import { Group, Panel, Separator } from 'react-resizable-panels'

import { activityLabelForPhase } from '@/lib/activity-phase'
import { AgentPane } from '@/components/AgentPane'
import { AgentChip } from '@/components/ui/agent-chip'
import { cn } from '@/lib/utils'
import { useMotionPreset } from '@/lib/motion'
import { resolveAgentRole } from '@/lib/agent-roles'
import { formatTokens } from '@/utils/format'
import type { AgentStream } from '@/stores/useTeamStore'
import type { ContentBlock, TodoItem } from '@/api/types'

interface SplitWorkbenchProps {
  agentNames: string[]
  leadName: string | null
  activeAgent: string | null
  agentStreams: Record<string, AgentStream>
  todos?: TodoItem[]
  isContinuing?: boolean
  onContinue?: () => void
  onSelectAgent: (name: string) => void
  showTurnChanges?: boolean
}

type RailFilter = 'all' | 'working' | 'issues'

const FILTERS: Array<{ value: RailFilter; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'working', label: 'Working' },
  { value: 'issues', label: 'Issues' },
]

function activeTool(blocks: ContentBlock[]): { name: string; args?: string } | null {
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index]
    if (block.type === 'tool' && !block.toolDone) {
      return { name: block.toolName ?? 'tool', args: block.toolArgs }
    }
  }
  return null
}

function truncate(value: string, max = 68): string {
  const normalized = value.replace(/\s+/g, ' ').trim()
  return normalized.length > max ? `${normalized.slice(0, max - 1)}…` : normalized
}

function toolSummary(tool: { name: string; args?: string } | null): string | null {
  if (!tool) return null
  if (!tool.args) return tool.name
  try {
    const parsed = JSON.parse(tool.args) as Record<string, unknown>
    const firstString = Object.values(parsed).find((value) => typeof value === 'string')
    return typeof firstString === 'string'
      ? `${tool.name} · ${truncate(firstString, 48)}`
      : tool.name
  } catch {
    return `${tool.name} · ${truncate(tool.args, 48)}`
  }
}

function latestActivity(stream: AgentStream): string {
  if (stream.status === 'error') return stream.lastError ? truncate(stream.lastError) : 'Agent error'
  const tool = toolSummary(activeTool(stream.currentBlocks))
  if (tool) return tool

  const blocks = stream.currentBlocks.length > 0 ? stream.currentBlocks : stream.blocks
  const last = blocks.at(-1)
  if (!last) {
    if (stream.status === 'working') {
      return `${activityLabelForPhase(stream.phase)}…`
    }
    if (stream.status === 'offline') return 'Offline'
    return 'No activity yet'
  }
  if (last.type === 'tool') return last.toolName ?? 'Tool call'
  return truncate(last.content || 'Activity updated')
}

function assignedTask(todos: TodoItem[] | undefined, name: string): TodoItem | null {
  if (!todos) return null
  const assigned = todos.filter((todo) => (todo.claimed_by ?? todo.assigned_to) === name)
  return (
    assigned.find((todo) => todo.status === 'in_progress') ??
    assigned.find((todo) => todo.status === 'pending') ??
    assigned.find((todo) => todo.status === 'completed') ??
    null
  )
}

function statusLabel(status: AgentStream['status']): string {
  if (status === 'working') return 'Working'
  if (status === 'error') return 'Issue'
  if (status === 'offline') return 'Offline'
  return 'Idle'
}

function statusDot(status: AgentStream['status']): string {
  if (status === 'working') return 'animate-pulse bg-(--color-accent)'
  if (status === 'error') return 'bg-(--color-error)'
  if (status === 'offline') return 'bg-(--color-text-subtle) opacity-45'
  return 'bg-(--color-success)'
}

function AgentRailItem({
  name,
  stream,
  task,
  isLead,
  selected,
  compared,
  onSelect,
  onCompare,
}: {
  name: string
  stream: AgentStream
  task: TodoItem | null
  isLead: boolean
  selected: boolean
  compared: boolean
  onSelect: () => void
  onCompare: () => void
}) {
  const canCompare = !selected
  const tokens = stream.usage.totalTokens
  const activity = latestActivity(stream)

  return (
    <div
      className={cn(
        'group relative overflow-hidden rounded-lg border bg-(--bg-card) transition-[border-color,background-color,box-shadow]',
        selected && 'border-(--color-accent)/55 bg-(--bg-key)/60 shadow-sm',
        compared && 'border-(--color-info)/55 bg-(--color-info)/5',
        !selected && !compared && 'border-(--color-border-subtle) hover:border-(--color-border)',
        stream.status === 'error' && 'border-(--color-error)/40',
      )}
    >
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className="block w-full pb-2.5 pl-3 pr-11 pt-3 text-left focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-(--color-accent)"
      >
        <div className="flex items-center gap-2">
          <AgentChip
            role={resolveAgentRole(name)}
            label={name}
            active={selected || compared}
            dotClassName={statusDot(stream.status)}
            className="min-w-0 flex-1 px-0 py-0"
          />
          {isLead && (
            <span className="shrink-0 rounded bg-(--bg-key) px-1.5 py-0.5 font-mono text-[10px] text-(--color-text-muted)">
              lead
            </span>
          )}
          <span
            className={cn(
              'shrink-0 text-[10px] font-medium',
              stream.status === 'error' ? 'text-(--color-error)' : 'text-(--color-text-subtle)',
            )}
          >
            {statusLabel(stream.status)}
          </span>
        </div>

        {task && (
          <div className="mt-2 flex items-center gap-1.5 text-[11px] text-(--color-text-2)">
            <CheckCircle2
              size={12}
              className={cn(
                'shrink-0',
                task.status === 'completed'
                  ? 'text-(--color-success)'
                  : task.status === 'in_progress'
                    ? 'text-(--color-accent)'
                    : 'text-(--color-text-subtle)',
              )}
              aria-hidden="true"
            />
            <span className="truncate" title={task.content}>{task.content}</span>
          </div>
        )}

        <div className="mt-1.5 flex items-center gap-1.5 text-[11px] text-(--color-text-muted)">
          {stream.status === 'error' ? (
            <AlertTriangle size={12} className="shrink-0 text-(--color-error)" aria-hidden="true" />
          ) : stream.status === 'working' ? (
            <Wrench size={12} className="shrink-0 text-(--color-accent)" aria-hidden="true" />
          ) : (
            <Activity size={12} className="shrink-0" aria-hidden="true" />
          )}
          <span className="min-w-0 flex-1 truncate" title={activity}>
            {activity}
          </span>
          <span className="shrink-0 font-mono text-[10px] tabular-nums text-(--color-text-subtle)">
            {tokens > 0 ? formatTokens(tokens) : '—'}
          </span>
        </div>
      </button>

      <button
        type="button"
        onClick={onCompare}
        disabled={!canCompare}
        aria-label={compared ? `Stop comparing ${name}` : `Compare with ${name}`}
        title={selected ? 'Focused agent' : compared ? 'Stop comparing' : 'Compare side by side'}
        className={cn(
          'absolute right-2 top-2 flex h-7 w-7 items-center justify-center rounded-md border border-transparent text-(--color-text-subtle) opacity-55 transition-[opacity,background-color,color,border-color] group-hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-(--color-accent)',
          canCompare && 'hover:border-(--color-border) hover:bg-(--bg-key) hover:text-(--color-text)',
          compared && 'border-(--color-info)/35 bg-(--color-info)/10 text-(--color-info) opacity-100',
          !canCompare && 'cursor-default',
        )}
      >
        {compared ? <X size={13} aria-hidden="true" /> : <Columns2 size={13} aria-hidden="true" />}
      </button>
    </div>
  )
}

function CompareResizeHandle() {
  return (
    <Separator className="group relative z-(--z-panel) flex w-2 cursor-col-resize items-center justify-center focus-visible:outline-none">
      <div className="h-12 w-0.5 rounded-full bg-(--color-border-subtle) transition-colors group-hover:bg-(--color-border-strong) group-data-[resize-handle-active]:bg-(--color-accent)" />
    </Separator>
  )
}

export function SplitWorkbench({
  agentNames,
  leadName,
  activeAgent,
  agentStreams,
  todos,
  isContinuing = false,
  onContinue,
  onSelectAgent,
  showTurnChanges = false,
}: SplitWorkbenchProps) {
  const preset = useMotionPreset()
  const [compareName, setCompareName] = useState<string | null>(null)
  const [railOpen, setRailOpen] = useState(true)
  const [filter, setFilter] = useState<RailFilter>('all')

  const visibleNames = useMemo(
    () => agentNames.filter((name) => agentStreams[name]?.status !== 'offline'),
    [agentNames, agentStreams],
  )

  const focusedName =
    (activeAgent && visibleNames.includes(activeAgent) ? activeAgent : null) ??
    (leadName && visibleNames.includes(leadName) ? leadName : null) ??
    visibleNames[0] ??
    ''
  const effectiveCompareName =
    compareName && compareName !== focusedName && visibleNames.includes(compareName)
      ? compareName
      : null
  const paneRenderKey = effectiveCompareName
    ? `${focusedName}:${effectiveCompareName}`
    : focusedName
  const [readyPaneKey, setReadyPaneKey] = useState<string | null>(null)
  const paneReady = readyPaneKey === paneRenderKey

  // Commit the inexpensive Split shell and team rail first. Transcript
  // Markdown mounts after the inexpensive shell has painted. Keep this state
  // update at normal priority so live streaming cannot starve it indefinitely.
  useEffect(() => {
    if (!paneRenderKey) return
    let secondFrame: number | null = null
    const firstFrame = requestAnimationFrame(() => {
      secondFrame = requestAnimationFrame(() => {
        setReadyPaneKey(paneRenderKey)
      })
    })
    return () => {
      cancelAnimationFrame(firstFrame)
      if (secondFrame !== null) cancelAnimationFrame(secondFrame)
    }
  }, [paneRenderKey])

  if (visibleNames.length === 0) return null

  const filteredNames = visibleNames.filter((name) => {
    const status = agentStreams[name]?.status
    if (filter === 'working') return status === 'working'
    if (filter === 'issues') return status === 'error'
    return true
  })
  const workingCount = visibleNames.filter((name) => agentStreams[name]?.status === 'working').length
  const issueCount = visibleNames.filter((name) => agentStreams[name]?.status === 'error').length

  const selectAgent = (name: string) => {
    if (name === effectiveCompareName) setCompareName(null)
    onSelectAgent(name)
  }

  const renderPane = (name: string) => {
    const stream = agentStreams[name]
    if (!stream) return null
    return (
      <motion.div
        key={name}
        initial={{ opacity: 0, y: 5 * preset.distance }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 5 * preset.distance }}
        transition={preset.transition}
        className="h-full min-h-0"
      >
        <AgentPane
          name={name}
          stream={stream}
          isLead={name === leadName}
          todos={todos}
          isContinuing={isContinuing && name === leadName}
          onContinue={name === leadName ? onContinue : undefined}
          collapsible={false}
          showTurnChanges={showTurnChanges}
        />
      </motion.div>
    )
  }

  return (
    <div className="flex h-full min-h-0 gap-2">
      <section className="flex min-w-0 flex-1 flex-col overflow-hidden" aria-label="Focused agents">
        <div className="mb-2 flex min-h-9 shrink-0 items-center gap-2 rounded-lg border border-(--color-border-subtle) bg-(--bg-card)/80 px-2.5">
          <div className="flex min-w-0 flex-1 items-center gap-2 text-xs">
            <span className="shrink-0 text-(--color-text-subtle)">Focus</span>
            <span className="truncate font-mono font-medium text-(--color-text)">{focusedName}</span>
            {effectiveCompareName && (
              <>
                <span className="text-(--color-text-subtle)">+</span>
                <span className="truncate font-mono font-medium text-(--color-info)">
                  {effectiveCompareName}
                </span>
              </>
            )}
          </div>
          {effectiveCompareName && (
            <button
              type="button"
              onClick={() => setCompareName(null)}
              className="flex h-7 items-center gap-1 rounded-md px-2 text-[11px] text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            >
              <X size={12} aria-hidden="true" />
              Exit compare
            </button>
          )}
          {!railOpen && (
            <button
              type="button"
              onClick={() => setRailOpen(true)}
              className="flex h-7 items-center gap-1.5 rounded-md border border-(--color-border) px-2 text-[11px] text-(--color-text-2) transition-colors hover:bg-(--bg-key)"
            >
              <PanelRightOpen size={13} aria-hidden="true" />
              Agents
            </button>
          )}
        </div>

        <div className="min-h-0 flex-1">
          {paneReady ? (
            <AnimatePresence initial={false} mode="popLayout">
              {effectiveCompareName ? (
                <motion.div
                  key={`compare:${focusedName}:${effectiveCompareName}`}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={preset.transition}
                  className="h-full"
                >
                  <Group orientation="horizontal" style={{ height: '100%' }}>
                    <Panel minSize={25} defaultSize={50} className="overflow-hidden">
                      {renderPane(focusedName)}
                    </Panel>
                    <CompareResizeHandle />
                    <Panel minSize={25} defaultSize={50} className="overflow-hidden">
                      {renderPane(effectiveCompareName)}
                    </Panel>
                  </Group>
                </motion.div>
              ) : (
                renderPane(focusedName)
              )}
            </AnimatePresence>
          ) : (
            <div
              className="flex h-full items-center justify-center rounded-lg border border-(--color-border-subtle) bg-(--bg-card)/35"
              role="status"
              aria-label="Preparing conversation"
            >
              <div className="flex items-center gap-2 text-xs text-(--color-text-muted)">
                <span className="h-3.5 w-3.5 animate-spin rounded-full border border-(--color-border-strong) border-t-(--color-accent)" />
                Preparing conversation…
              </div>
            </div>
          )}
        </div>
      </section>

      <AnimatePresence initial={false}>
        {railOpen && (
          <motion.aside
            initial={{ opacity: 0, x: 14 * preset.distance }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 14 * preset.distance }}
            transition={preset.spring}
            className="flex w-72 shrink-0 flex-col overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-card)/70 shadow-sm"
            aria-label="Team agents"
          >
            <div className="shrink-0 border-b border-(--color-border-subtle) px-3 pb-2.5 pt-3">
              <div className="flex items-center gap-2">
                <div className="min-w-0 flex-1">
                  <h2 className="text-sm font-semibold text-(--color-text)">Agents</h2>
                  <p className="mt-0.5 text-[11px] text-(--color-text-muted)">
                    {visibleNames.length} total
                    {workingCount > 0 && ` · ${workingCount} working`}
                    {issueCount > 0 && ` · ${issueCount} issue${issueCount === 1 ? '' : 's'}`}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setRailOpen(false)}
                  aria-label="Hide agent list"
                  title="Hide agent list"
                  className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                >
                  <PanelRightClose size={15} aria-hidden="true" />
                </button>
              </div>

              <div className="mt-2.5 flex items-center gap-1" aria-label="Filter agents">
                {FILTERS.map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    onClick={() => setFilter(item.value)}
                    aria-pressed={filter === item.value}
                    className={cn(
                      'rounded-md px-2 py-1 text-[10px] font-medium transition-colors',
                      filter === item.value
                        ? 'bg-(--bg-key) text-(--color-text)'
                        : 'text-(--color-text-subtle) hover:bg-(--bg-key)/60 hover:text-(--color-text-2)',
                    )}
                  >
                    {item.label}
                    {item.value === 'working' && workingCount > 0 && ` ${workingCount}`}
                    {item.value === 'issues' && issueCount > 0 && ` ${issueCount}`}
                  </button>
                ))}
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-2">
              {filteredNames.length > 0 ? (
                <div className="space-y-1.5">
                  {filteredNames.map((name) => {
                    const stream = agentStreams[name]
                    if (!stream) return null
                    return (
                      <AgentRailItem
                        key={name}
                        name={name}
                        stream={stream}
                        task={assignedTask(todos, name)}
                        isLead={name === leadName}
                        selected={name === focusedName}
                        compared={name === effectiveCompareName}
                        onSelect={() => selectAgent(name)}
                        onCompare={() =>
                          setCompareName((current) => (current === name ? null : name))
                        }
                      />
                    )
                  })}
                </div>
              ) : (
                <div className="flex h-32 flex-col items-center justify-center px-4 text-center">
                  <p className="text-xs font-medium text-(--color-text-2)">No matching agents</p>
                  <button
                    type="button"
                    onClick={() => setFilter('all')}
                    className="mt-1.5 text-[11px] text-(--color-accent) hover:underline"
                  >
                    Show all agents
                  </button>
                </div>
              )}
            </div>

            <div className="shrink-0 border-t border-(--color-border-subtle) px-3 py-2 text-[10px] leading-4 text-(--color-text-subtle)">
              Select an agent to focus. Use <Columns2 size={11} className="inline align-[-2px]" aria-hidden="true" /> to compare.
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    </div>
  )
}
