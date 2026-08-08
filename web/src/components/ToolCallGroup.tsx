/**
 * ToolCallGroup — collapses a consecutive agent activity run into one row.
 *
 * Tools from one uninterrupted activity phase are grouped from the moment the
 * first call starts. Thinking/text remain visible boundaries, while pending →
 * completed state changes never re-parent the activity row. Expanding preserves
 * the original ordered detail through the shared `BlockRenderer` pipeline.
 *
 * Latest MCP app UIs stay visible while collapsed — interactive surfaces
 * should not require expand just to remain usable.
 */

import { memo, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Terminal, FileText, Search, Globe, Code2,
  FolderOpen, GitBranch, Database, ChevronDown, ChevronUp,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { ToolAttachments } from './ToolCall'
import { BlockRenderer } from './BlockRenderer'
import { MCPAppResult } from './MCPAppResult'
import { ActivityStatus } from './motion/ActivityStatus'
import { mcpAppResourceUri } from '@/utils/mcp-app-artifacts'
import { panelTransition, useMotionPreset } from '@/lib/motion'
import type { ContentBlock, MessageAttachment } from '@/api/types'
import { getSkillCallPresentation } from './ToolCall/skillPresentation'

// ── Grouped block type ────────────────────────────────────────────────────────

export interface ToolBlockGroup {
  kind: 'group'
  id: string
  toolName: string
  blocks: ContentBlock[]
}

export type RenderBlock = ContentBlock | ToolBlockGroup

// ── Tool icon & label helpers ────────────────────────────────────────────────

interface ToolPresentation {
  icon: React.ElementType
  verb: string
  singular: string
  plural: string
}

const TOOL_PRESENTATION: Record<string, ToolPresentation> = {
  bash: { icon: Terminal, verb: 'Ran', singular: 'shell command', plural: 'shell commands' },
  shell: { icon: Terminal, verb: 'Ran', singular: 'shell command', plural: 'shell commands' },
  run_command: { icon: Terminal, verb: 'Ran', singular: 'shell command', plural: 'shell commands' },
  python: { icon: Code2, verb: 'Ran', singular: 'Python call', plural: 'Python calls' },
  read: { icon: FileText, verb: 'Read', singular: 'file', plural: 'files' },
  read_file: { icon: FileText, verb: 'Read', singular: 'file', plural: 'files' },
  write: { icon: FileText, verb: 'Wrote', singular: 'file', plural: 'files' },
  write_file: { icon: FileText, verb: 'Wrote', singular: 'file', plural: 'files' },
  edit: { icon: FileText, verb: 'Edited', singular: 'file', plural: 'files' },
  edit_file: { icon: FileText, verb: 'Edited', singular: 'file', plural: 'files' },
  patch: { icon: FileText, verb: 'Patched', singular: 'file', plural: 'files' },
  glob: { icon: FolderOpen, verb: 'Listed', singular: 'directory', plural: 'directories' },
  ls: { icon: FolderOpen, verb: 'Listed', singular: 'directory', plural: 'directories' },
  grep: { icon: Search, verb: 'Searched', singular: 'search', plural: 'searches' },
  code_context: { icon: Database, verb: 'Queried', singular: 'code-context call', plural: 'code-context calls' },
  browser_use: { icon: Globe, verb: 'Browsed', singular: 'browser call', plural: 'browser calls' },
  webbridge: { icon: Globe, verb: 'Browsed', singular: 'browser call', plural: 'browser calls' },
  git: { icon: GitBranch, verb: 'Ran', singular: 'Git call', plural: 'Git calls' },
}

const DEFAULT_PRESENTATION: ToolPresentation = {
  icon: Terminal,
  verb: 'Called',
  singular: 'call',
  plural: 'calls',
}

// eslint-disable-next-line react-refresh/only-export-components
export function getToolIcon(toolName: string): React.ElementType {
  return TOOL_PRESENTATION[toolName]?.icon ?? DEFAULT_PRESENTATION.icon
}

// ── Grouping utility ─────────────────────────────────────────────────────────

const FILE_ACTIVITY_TOOLS = new Set([
  'read',
  'read_file',
  'glob',
  'ls',
  'grep',
  'code_context',
])
const BROWSER_ACTIVITY_TOOLS = new Set(['browser_use', 'webbridge'])
const SHELL_ACTIVITY_TOOLS = new Set(['bash', 'shell', 'run_command'])
const WRITE_ACTIVITY_TOOLS = new Set([
  'write',
  'write_file',
  'edit',
  'edit_file',
  'patch',
])

function toolFamily(block: ContentBlock): string {
  const toolName = block.toolName ?? ''
  if (FILE_ACTIVITY_TOOLS.has(toolName)) return 'files'
  if (BROWSER_ACTIVITY_TOOLS.has(toolName)) return 'browser'
  if (SHELL_ACTIVITY_TOOLS.has(toolName)) return 'shell'
  if (WRITE_ACTIVITY_TOOLS.has(toolName)) return 'write'
  if (toolName === 'skill') {
    return getSkillCallPresentation(block.toolArgs)?.family ?? 'skill'
  }
  return toolName
}

function familyLabel(family: string): string {
  switch (family) {
    case 'files': return 'Read files'
    case 'browser': return 'Browsed web'
    case 'shell': return 'Ran commands'
    case 'write': return 'Changed files'
    case 'python': return 'Ran Python'
    case 'git': return 'Ran Git'
    case 'skill-load': return 'Loaded a skill'
    case 'skill-resource': return 'Read skill resources'
    case 'skill-list': return 'Listed skills'
    case 'skill': return 'Used skill tool'
    default: return 'Used tools'
  }
}

// eslint-disable-next-line react-refresh/only-export-components
export function groupLabel(blocks: ContentBlock[]): string {
  const families = [...new Set(blocks.flatMap((block) => (
    block.toolName ? [toolFamily(block)] : []
  )))]
  const labels = families.map(familyLabel)
  return labels
    .map((label, index) => index === 0 ? label : label.charAt(0).toLowerCase() + label.slice(1))
    .join(', ')
}

// eslint-disable-next-line react-refresh/only-export-components
export function groupConsecutiveToolCalls(blocks: ContentBlock[]): RenderBlock[] {
  const result: RenderBlock[] = []
  let i = 0

  while (i < blocks.length) {
    const block = blocks[i]
    if (block.type !== 'tool' || !block.toolName) {
      result.push(block)
      i++
      continue
    }

    // Give an activity run its final container as soon as the first tool-call
    // delta arrives. Waiting for completion (and a second tool) used to
    // re-parent the same ToolCall from a standalone row into a group after it
    // finished, which caused a visible layout jump during bottom-follow.
    // Reasoning/text remains the boundary; completion state does not.
    let j = i + 1
    while (
      j < blocks.length &&
      blocks[j].type === 'tool' &&
      Boolean(blocks[j].toolName)
    ) {
      j++
    }

    const activityBlocks = blocks.slice(i, j)
    result.push({
      kind: 'group',
      id: `tool-group-${block.id}`,
      toolName: block.toolName,
      blocks: activityBlocks,
    })
    i = j
  }

  return result
}

// ── Component ─────────────────────────────────────────────────────────────────

interface ToolCallGroupProps {
  group: ToolBlockGroup
  agentName?: string | null
  className?: string
  isStreaming?: boolean
  sessionId?: string
  latestMCPAppBlockIds?: Set<string>
  compact?: boolean
}

function sameGroupBlocks(left: ToolBlockGroup, right: ToolBlockGroup): boolean {
  return left.id === right.id
    && left.toolName === right.toolName
    && left.blocks.length === right.blocks.length
    && left.blocks.every((block, index) => block === right.blocks[index])
}

export const ToolCallGroupCard = memo(function ToolCallGroupCard({
  group,
  className,
  isStreaming = false,
  sessionId,
  latestMCPAppBlockIds,
  compact = false,
}: ToolCallGroupProps) {
  const preset = useMotionPreset()
  const [expanded, setExpanded] = useState(false)
  const activityScrollRef = useRef<HTMLDivElement>(null)
  const toolBlocks = group.blocks.filter((block) => block.type === 'tool')
  const delegationBlocks = toolBlocks.filter((block) => block.toolName === 'team_delegate')
  const detailBlocks = toolBlocks.filter((block) => block.toolName !== 'team_delegate')
  /* eslint-disable react-hooks/static-components */
  const Icon = getToolIcon(detailBlocks[0]?.toolName ?? group.toolName)
  const label = groupLabel(detailBlocks)
  const actionLabel = `${detailBlocks.length} ${detailBlocks.length === 1 ? 'action' : 'actions'}`
  const groupIsStreaming = isStreaming && detailBlocks.some((block) => !block.toolDone)
  const delegationIsStreaming = isStreaming && delegationBlocks.some((block) => !block.toolDone)
  const groupedAttachments = detailBlocks.flatMap(
    (block) =>
      (block.extra as { attachments?: MessageAttachment[] } | undefined)
        ?.attachments ?? [],
  )

  useEffect(() => {
    if (!expanded || !isStreaming) return
    const element = activityScrollRef.current
    if (element) element.scrollTop = element.scrollHeight
  }, [expanded, group.blocks.length, isStreaming])

  const collapsedMcpApps = (() => {
    if (expanded || !latestMCPAppBlockIds || latestMCPAppBlockIds.size === 0) {
      return []
    }
    return detailBlocks.flatMap((block) => {
      if (!block.toolDone || !latestMCPAppBlockIds.has(block.id)) return []
      const mcpApp = (block.extra as { mcp_app?: unknown } | undefined)?.mcp_app
      if (!mcpApp || !mcpAppResourceUri(block)) return []
      return [{ blockId: block.id, toolCallId: block.toolCallId, mcpApp }]
    })
  })()

  return (
    <div className={cn('relative overflow-hidden rounded-md', className)}>
      {detailBlocks.length > 0 && (
        <>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className={cn(
              'flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left',
              'hover:bg-(--bg-key) transition-colors',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)',
            )}
            aria-expanded={expanded}
            aria-label={`${expanded ? 'Collapse' : 'Expand'} ${label}, ${actionLabel}`}
          >
            <Icon className="h-3.5 w-3.5 shrink-0 text-(--color-text-muted)" />
            {/* eslint-enable react-hooks/static-components */}
            <span className="flex-1 text-xs text-(--color-text-muted)">
              <span className="font-medium text-(--color-text-2)">{label}</span>
              <AnimatePresence initial={false} mode="popLayout">
                <motion.span
                  key={detailBlocks.length}
                  initial={preset.intensity === 'reduced' ? false : { opacity: 0, y: 3 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={preset.intensity === 'reduced' ? undefined : { opacity: 0, y: -3 }}
                  transition={preset.transition}
                  className="ml-1 inline-block text-(--color-text-subtle)"
                >
                  · {detailBlocks.length} {detailBlocks.length === 1 ? 'action' : 'actions'}
                </motion.span>
              </AnimatePresence>
              {groupIsStreaming && (
                <ActivityStatus label="Running" className="ml-1 text-xs" />
              )}
            </span>
            {expanded ? (
              <ChevronUp className="h-3 w-3 text-(--color-text-muted)" aria-hidden="true" />
            ) : (
              <ChevronDown className="h-3 w-3 text-(--color-text-muted)" aria-hidden="true" />
            )}
          </button>

          {!expanded && groupedAttachments.length > 0 && (
            <div className="px-3 pb-2">
              <ToolAttachments attachments={groupedAttachments} limit={4} />
            </div>
          )}

          {!expanded && collapsedMcpApps.length > 0 && (
            <div className="space-y-2 px-3 pb-2">
              {collapsedMcpApps.map(({ blockId, toolCallId, mcpApp }) => (
                <MCPAppResult
                  key={blockId}
                  mcpApp={mcpApp as never}
                  sessionId={sessionId}
                  toolCallId={toolCallId}
                />
              ))}
            </div>
          )}

          <AnimatePresence initial={false}>
            {expanded && (
              <motion.div
                key="activity-details"
                initial={preset.intensity === 'reduced' ? false : { height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={preset.intensity === 'reduced' ? undefined : { height: 0, opacity: 0 }}
                transition={panelTransition(preset)}
                className="overflow-hidden"
              >
                <div ref={activityScrollRef} className="activity-group-scroll px-1">
                  {detailBlocks.map((block, index) => (
                    <motion.div
                      key={block.id}
                      initial={preset.intensity === 'reduced'
                        ? false
                        : { opacity: 0, x: -4, y: 7, filter: 'blur(2px)' }}
                      animate={{ opacity: 1, x: 0, y: 0, filter: 'blur(0px)' }}
                      transition={preset.intensity === 'reduced'
                        ? { duration: 0 }
                        : {
                            ...preset.spring,
                            delay: Math.min(index, 8) * Math.max(preset.stagger * 1.5, 0.035),
                          }}
                      className="activity-group-row"
                    >
                      <BlockRenderer
                        block={block}
                        isStreaming={groupIsStreaming && index === detailBlocks.length - 1}
                        sessionId={sessionId}
                        latestMCPAppBlockIds={latestMCPAppBlockIds}
                        compact={compact}
                      />
                    </motion.div>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </>
      )}

      {delegationBlocks.map((block, index) => (
        <BlockRenderer
          key={block.id}
          block={block}
          isStreaming={delegationIsStreaming && index === delegationBlocks.length - 1}
          sessionId={sessionId}
          latestMCPAppBlockIds={latestMCPAppBlockIds}
          compact={compact}
        />
      ))}
    </div>
  )
}, (previous, next) => (
  sameGroupBlocks(previous.group, next.group)
  && previous.className === next.className
  && previous.isStreaming === next.isStreaming
  && previous.sessionId === next.sessionId
  && previous.latestMCPAppBlockIds === next.latestMCPAppBlockIds
  && previous.compact === next.compact
))
