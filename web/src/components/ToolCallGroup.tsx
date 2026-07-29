/**
 * ToolCallGroup — collapses N consecutive same-tool calls into one row.
 *
 * Shows: "[icon] Read file × 12  ▾"
 * Expanding reveals each individual ToolCall card.
 */

import { useState } from 'react'
import {
  Terminal, FileText, Search, Globe, Code2,
  FolderOpen, GitBranch, Database, ChevronDown, ChevronUp,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { ToolAttachments, ToolCall } from './ToolCall'
import { ActivityStatus } from './motion/ActivityStatus'
import type { ContentBlock, MessageAttachment } from '@/api/types'

// ── Grouped block type ────────────────────────────────────────────────────────

export interface ToolBlockGroup {
  kind: 'group'
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

function getToolVerb(toolName: string): string {
  return TOOL_PRESENTATION[toolName]?.verb ?? DEFAULT_PRESENTATION.verb
}

function getResourceLabel(toolName: string, count: number): string {
  const presentation = TOOL_PRESENTATION[toolName] ?? DEFAULT_PRESENTATION
  return count === 1 ? presentation.singular : presentation.plural
}

// ── Grouping utility ─────────────────────────────────────────────────────────

const MIN_GROUP_SIZE = 3

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

    // Count consecutive tool blocks with the same toolName
    let j = i + 1
    while (
      j < blocks.length &&
      blocks[j].type === 'tool' &&
      blocks[j].toolName === block.toolName
    ) {
      j++
    }

    const count = j - i
    if (count >= MIN_GROUP_SIZE) {
      result.push({
        kind: 'group',
        toolName: block.toolName,
        blocks: blocks.slice(i, j),
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
}

export function ToolCallGroupCard({ group, className }: ToolCallGroupProps) {
  const [expanded, setExpanded] = useState(false)
  /* eslint-disable react-hooks/static-components */
  const Icon = getToolIcon(group.toolName)
  const verb = getToolVerb(group.toolName)
  const resource = getResourceLabel(group.toolName, group.blocks.length)
  const allDone = group.blocks.every((b) => b.toolDone)
  const groupedAttachments = group.blocks.flatMap(
    (block) =>
      (block.extra as { attachments?: MessageAttachment[] } | undefined)
        ?.attachments ?? [],
  )

  return (
    <div className={cn('rounded-md border overflow-hidden', className)}>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className={cn(
          'flex w-full items-center gap-2 px-3 py-2 text-left',
          'bg-(--bg-subtle) hover:bg-(--bg-hover) transition-colors',
        )}
      >
        <Icon className="h-3.5 w-3.5 shrink-0 text-(--color-text-muted)" />
        {/* eslint-enable react-hooks/static-components */}
        <span className="flex-1 text-xs text-(--color-text-muted)">
          <span className="font-medium text-(--color-text)">{verb}</span>{' '}
          {group.blocks.length} {resource}
          {!allDone && <ActivityStatus label="Running" className="ml-1 text-xs" />}
        </span>
        {expanded ? (
          <ChevronUp className="h-3 w-3 text-(--color-text-muted)" />
        ) : (
          <ChevronDown className="h-3 w-3 text-(--color-text-muted)" />
        )}
      </button>

      {!expanded && groupedAttachments.length > 0 && (
        <div className="px-3 pb-2">
          <ToolAttachments attachments={groupedAttachments} limit={4} />
        </div>
      )}

      {expanded && (
        <div className="divide-y">
          {group.blocks.map((block) => (
            <div key={block.id} className="px-2 py-1">
              <ToolCall
                name={block.toolName || ''}
                args={block.toolArgs}
                done={block.toolDone}
                liveOutput={block.toolOutput}
                result={block.toolResult}
                durationMs={block.durationMs}
                startedAt={block.startedAt}
                attachments={
                  (block.extra as { attachments?: MessageAttachment[] } | undefined)
                    ?.attachments
                }
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
