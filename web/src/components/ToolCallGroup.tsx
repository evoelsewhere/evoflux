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
import { ToolCall } from './ToolCall'
import type { ContentBlock } from '@/api/types'

// ── Grouped block type ────────────────────────────────────────────────────────

export interface ToolBlockGroup {
  kind: 'group'
  toolName: string
  blocks: ContentBlock[]
}

export type RenderBlock = ContentBlock | ToolBlockGroup

// ── Tool icon & label helpers ────────────────────────────────────────────────

const TOOL_ICON_MAP: Record<string, React.ElementType> = {
  bash: Terminal,
  shell: Terminal,
  run_command: Terminal,
  read_file: FileText,
  write_file: FileText,
  edit_file: FileText,
  glob: FolderOpen,
  grep: Search,
  search: Search,
  code_graph: Database,
  browser: Globe,
  git: GitBranch,
  python: Code2,
}

function getToolIcon(toolName: string): React.ElementType {
  const lower = toolName.toLowerCase()
  for (const [key, Icon] of Object.entries(TOOL_ICON_MAP)) {
    if (lower.includes(key)) return Icon
  }
  return Terminal
}

function getToolVerb(toolName: string): string {
  const lower = toolName.toLowerCase()
  if (lower.includes('read') || lower.includes('glob') || lower.includes('ls')) return 'Read'
  if (lower.includes('write') || lower.includes('edit') || lower.includes('create')) return 'Wrote'
  if (lower.includes('grep') || lower.includes('search')) return 'Searched'
  if (lower.includes('bash') || lower.includes('shell') || lower.includes('run')) return 'Ran'
  if (lower.includes('browser')) return 'Browsed'
  return 'Called'
}

function getResourceLabel(toolName: string, count: number): string {
  const lower = toolName.toLowerCase()
  if (lower.includes('file')) return count === 1 ? 'file' : 'files'
  if (lower.includes('bash') || lower.includes('shell') || lower.includes('run')) {
    return count === 1 ? 'shell command' : 'shell commands'
  }
  if (lower.includes('grep') || lower.includes('search')) {
    return count === 1 ? 'search' : 'searches'
  }
  if (lower.includes('glob') || lower.includes('ls')) {
    return count === 1 ? 'directory' : 'directories'
  }
  return count === 1 ? 'call' : 'calls'
}

// ── Grouping utility ─────────────────────────────────────────────────────────

const MIN_GROUP_SIZE = 3

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
  const Icon = getToolIcon(group.toolName)
  const verb = getToolVerb(group.toolName)
  const resource = getResourceLabel(group.toolName, group.blocks.length)
  const allDone = group.blocks.every((b) => b.toolDone)

  return (
    <div className={cn('rounded-md border border-(--border-subtle) overflow-hidden', className)}>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className={cn(
          'flex w-full items-center gap-2 px-3 py-2 text-left',
          'bg-(--bg-subtle) hover:bg-(--bg-hover) transition-colors',
        )}
      >
        <Icon className="h-3.5 w-3.5 shrink-0 text-(--color-text-muted)" />
        <span className="flex-1 text-xs text-(--color-text-muted)">
          <span className="font-medium text-(--color-text)">{verb}</span>{' '}
          {group.blocks.length} {resource}
          {!allDone && (
            <span className="ml-1 text-amber-400">(running…)</span>
          )}
        </span>
        {expanded ? (
          <ChevronUp className="h-3 w-3 text-(--color-text-muted)" />
        ) : (
          <ChevronDown className="h-3 w-3 text-(--color-text-muted)" />
        )}
      </button>

      {expanded && (
        <div className="divide-y divide-(--border-subtle)">
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
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
