/**
 * ToolCallGroup — collapses a consecutive agent activity run into one row.
 *
 * Only completed tools from one semantic family are grouped. Thinking and
 * in-flight tools remain visible boundaries so live activity stays legible.
 * Expanding preserves the original ordered detail through the shared
 * `BlockRenderer` pipeline (tools and MCP apps).
 *
 * Latest MCP app UIs stay visible while collapsed — interactive surfaces
 * should not require expand just to remain usable.
 */

import { useMemo, useState } from 'react'
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
import type { ContentBlock, MessageAttachment } from '@/api/types'

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
  code_search: { icon: Search, verb: 'Searched', singular: 'search', plural: 'searches' },
  code_graph: { icon: Database, verb: 'Queried', singular: 'graph call', plural: 'graph calls' },
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

const MIN_GROUP_SIZE = 3
const FILE_ACTIVITY_TOOLS = new Set([
  'read',
  'read_file',
  'glob',
  'ls',
  'grep',
  'code_search',
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

function toolFamily(toolName: string): string {
  if (FILE_ACTIVITY_TOOLS.has(toolName)) return 'files'
  if (BROWSER_ACTIVITY_TOOLS.has(toolName)) return 'browser'
  if (SHELL_ACTIVITY_TOOLS.has(toolName)) return 'shell'
  if (WRITE_ACTIVITY_TOOLS.has(toolName)) return 'write'
  return toolName
}

function groupLabel(toolName: string): string {
  switch (toolFamily(toolName)) {
    case 'files': return 'Read files'
    case 'browser': return 'Browsed web'
    case 'shell': return 'Ran commands'
    case 'write': return 'Changed files'
    default: return 'Ran tools'
  }
}

// eslint-disable-next-line react-refresh/only-export-components
export function groupConsecutiveToolCalls(blocks: ContentBlock[]): RenderBlock[] {
  const result: RenderBlock[] = []
  let i = 0

  while (i < blocks.length) {
    const block = blocks[i]
    if (block.type !== 'tool' || !block.toolName || !block.toolDone) {
      result.push(block)
      i++
      continue
    }

    // Only collapse completed tools from one semantic family. Thinking and
    // in-flight tools remain visible boundaries while the response streams.
    const family = toolFamily(block.toolName)
    let j = i + 1
    while (
      j < blocks.length &&
      blocks[j].type === 'tool' &&
      Boolean(blocks[j].toolName) &&
      blocks[j].toolDone === true &&
      toolFamily(blocks[j].toolName as string) === family
    ) {
      j++
    }

    const activityBlocks = blocks.slice(i, j)
    if (activityBlocks.length >= MIN_GROUP_SIZE) {
      result.push({
        kind: 'group',
        id: `tool-group-${block.id}`,
        toolName: block.toolName,
        blocks: activityBlocks,
      })
    } else {
      for (let k = i; k < j; k++) {
        result.push(blocks[k])
      }
    }
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

export function ToolCallGroupCard({
  group,
  className,
  isStreaming = false,
  sessionId,
  latestMCPAppBlockIds,
  compact = false,
}: ToolCallGroupProps) {
  const [expanded, setExpanded] = useState(false)
  /* eslint-disable react-hooks/static-components */
  const Icon = getToolIcon(group.toolName)
  const toolBlocks = group.blocks.filter((block) => block.type === 'tool')
  const label = groupLabel(group.toolName)
  const groupIsStreaming = isStreaming && toolBlocks.some((block) => !block.toolDone)
  const groupedAttachments = toolBlocks.flatMap(
    (block) =>
      (block.extra as { attachments?: MessageAttachment[] } | undefined)
        ?.attachments ?? [],
  )

  const collapsedMcpApps = useMemo(() => {
    if (expanded || !latestMCPAppBlockIds || latestMCPAppBlockIds.size === 0) {
      return []
    }
    return toolBlocks.flatMap((block) => {
      if (!block.toolDone || !latestMCPAppBlockIds.has(block.id)) return []
      const mcpApp = (block.extra as { mcp_app?: unknown } | undefined)?.mcp_app
      if (!mcpApp || !mcpAppResourceUri(block)) return []
      return [{ blockId: block.id, toolCallId: block.toolCallId, mcpApp }]
    })
  }, [expanded, latestMCPAppBlockIds, toolBlocks])

  return (
    <div className={cn('overflow-hidden rounded-md', className)}>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className={cn(
          'flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left',
          'hover:bg-(--bg-key) transition-colors',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)',
        )}
        aria-expanded={expanded}
        aria-label={`${expanded ? 'Collapse' : 'Expand'} ${label}, ${toolBlocks.length} actions`}
      >
        <Icon className="h-3.5 w-3.5 shrink-0 text-(--color-text-muted)" />
        {/* eslint-enable react-hooks/static-components */}
        <span className="flex-1 text-xs text-(--color-text-muted)">
          <span className="font-medium text-(--color-text-2)">{label}</span>
          <span className="ml-1 text-(--color-text-subtle)">
            · {toolBlocks.length} actions
          </span>
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

      {expanded && (
        <div className="ml-2 border-l border-(--color-border) pl-2">
          {group.blocks.map((block, index) => (
            <div key={block.id} className="py-0.5">
              <BlockRenderer
                block={block}
                isStreaming={groupIsStreaming && index === group.blocks.length - 1}
                sessionId={sessionId}
                latestMCPAppBlockIds={latestMCPAppBlockIds}
                compact={compact}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
