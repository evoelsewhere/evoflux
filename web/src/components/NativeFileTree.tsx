/**
 * NativeFileTree — lazy-loading file tree using Tauri native filesystem.
 *
 * Desktop-only component that loads directory contents on-demand when
 * the user clicks to expand a folder. This provides:
 *
 * - Instant initial load (only root directory)
 * - No file count limit
 * - Better performance for large repositories
 * - Native filesystem access (no HTTP proxy)
 * - Virtual scrolling for directories with >100 files
 */

import { useCallback, useEffect, useState } from 'react'
import { FixedSizeList as VirtualList } from 'react-window'
import {
  ChevronRight,
  FileText,
  Folder,
  FolderOpen,
  Loader2,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { tauriListDirectory, type DirEntry } from '@/api/tauri-workspace'
import { formatBytes } from '@/utils/format'

// Threshold for enabling virtual scrolling
const VIRTUAL_SCROLL_THRESHOLD = 100

// ── Types ────────────────────────────────────────────────────────────────────

interface TreeNode {
  entry: DirEntry
  children: TreeNode[] | null // null = not loaded yet
  isExpanded: boolean
}

interface NativeFileTreeProps {
  /** Absolute path to workspace root */
  workspaceRoot: string
  /** Currently selected file path */
  selectedPath?: string | null
  /** Callback when a file is selected */
  onFileSelect?: (entry: DirEntry | null) => void
  /** Optional className */
  className?: string
}

// ── Tree Node Component ──────────────────────────────────────────────────────

function TreeNodeItem({
  node,
  depth,
  selectedPath,
  onFileSelect,
  onToggle,
}: {
  node: TreeNode
  depth: number
  selectedPath?: string | null
  onFileSelect?: (entry: DirEntry | null) => void
  onToggle: (path: string) => void
}) {
  const { entry, children, isExpanded } = node
  const isSelected = entry.path === selectedPath

  const handleClick = useCallback(() => {
    if (entry.is_dir) {
      onToggle(entry.path)
    } else {
      onFileSelect?.(isSelected ? null : entry)
    }
  }, [entry, isSelected, onFileSelect, onToggle])

  const handleExpand = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation()
      if (entry.is_dir) {
        onToggle(entry.path)
      }
    },
    [entry.is_dir, entry.path, onToggle],
  )

  return (
    <div>
      <button
        type="button"
        onClick={handleClick}
        className={cn(
          'flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-xs transition-colors',
          isSelected
            ? 'bg-(--bg-key) text-(--color-accent)'
            : 'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)',
        )}
        style={{ paddingLeft: 8 + depth * 16 }}
        title={entry.path}
      >
        {entry.is_dir ? (
          <>
            <button
              type="button"
              onClick={handleExpand}
              className="flex shrink-0 items-center justify-center w-4 h-4"
            >
              <ChevronRight
                size={12}
                className={cn('transition-transform', isExpanded && 'rotate-90')}
              />
            </button>
            {isExpanded ? (
              <FolderOpen size={12} className="shrink-0 text-(--color-accent)" />
            ) : (
              <Folder size={12} className="shrink-0 text-(--color-text-subtle)" />
            )}
          </>
        ) : (
          <>
            <span className="w-4 shrink-0" />
            <FileText size={12} className="shrink-0 text-(--color-text-subtle)" />
          </>
        )}
        <span className="min-w-0 flex-1 truncate font-mono">{entry.name}</span>
        {!entry.is_dir && (
          <span className="shrink-0 text-xs text-(--color-text-subtle)">
            {formatBytes(entry.size)}
          </span>
        )}
      </button>

      {entry.is_dir && isExpanded && children && (
        <div>
          {children.map((child) => (
            <TreeNodeItem
              key={child.entry.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              onFileSelect={onFileSelect}
              onToggle={onToggle}
            />
          ))}
        </div>
      )}

      {entry.is_dir && isExpanded && node.children === null && (
        <div
          className="flex items-center gap-1.5 px-2 py-1 text-xs text-(--color-text-subtle)"
          style={{ paddingLeft: 8 + (depth + 1) * 16 }}
        >
          <Loader2 size={12} className="animate-spin" />
          <span>Loading…</span>
        </div>
      )}
    </div>
  )
}

// ── Main Component ───────────────────────────────────────────────────────────

export function NativeFileTree({
  workspaceRoot,
  selectedPath,
  onFileSelect,
  className,
}: NativeFileTreeProps) {
  const [rootEntries, setRootEntries] = useState<DirEntry[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set())
  const [dirChildren, setDirChildren] = useState<Map<string, DirEntry[]>>(new Map())

  // Load root directory on mount
  useEffect(() => {
    let cancelled = false

    async function loadRoot() {
      try {
        const result = await tauriListDirectory(workspaceRoot, '')
        if (!cancelled) {
          setRootEntries(result.entries)
          setLoading(false)
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e))
          setLoading(false)
        }
      }
    }

    void loadRoot()

    return () => {
      cancelled = true
    }
  }, [workspaceRoot])

  // Toggle directory expansion
  const handleToggle = useCallback(
    async (dirPath: string) => {
      if (expandedDirs.has(dirPath)) {
        // Collapse
        setExpandedDirs((prev) => {
          const next = new Set(prev)
          next.delete(dirPath)
          return next
        })
        return
      }

      // Expand
      setExpandedDirs((prev) => new Set(prev).add(dirPath))

      // Load children if not cached
      if (!dirChildren.has(dirPath)) {
        try {
          const result = await tauriListDirectory(workspaceRoot, dirPath)
          setDirChildren((prev) => new Map(prev).set(dirPath, result.entries))
        } catch (e) {
          console.error('Failed to load directory:', e)
        }
      }
    },
    [expandedDirs, dirChildren, workspaceRoot],
  )

  // Build tree nodes from entries
  const buildTreeNodes = useCallback(
    (entries: DirEntry[]): TreeNode[] => {
      return entries.map((entry) => ({
        entry,
        children: entry.is_dir ? (dirChildren.get(entry.path) ?? null) : null,
        isExpanded: expandedDirs.has(entry.path),
      }))
    },
    [dirChildren, expandedDirs],
  )

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 px-4 py-8 text-xs text-(--color-text-subtle)">
        <Loader2 size={14} className="animate-spin" />
        <span>Loading files…</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="px-4 py-4 text-xs text-(--color-error)">
        {error}
      </div>
    )
  }

  if (!rootEntries || rootEntries.length === 0) {
    return (
      <div className="px-4 py-4 text-xs text-(--color-text-subtle)">
        No files found
      </div>
    )
  }

  const treeNodes = buildTreeNodes(rootEntries)

  // Use virtual scrolling for large directories
  if (treeNodes.length > VIRTUAL_SCROLL_THRESHOLD) {
    const ITEM_HEIGHT = 28 // px per row
    return (
      <div className={cn('overflow-auto', className)}>
        <VirtualList
          height={Math.min(600, treeNodes.length * ITEM_HEIGHT)} // max 600px
          itemCount={treeNodes.length}
          itemSize={ITEM_HEIGHT}
          width="100%"
        >
          {({ index, style }) => (
            <div style={style}>
              <TreeNodeItem
                node={treeNodes[index]}
                depth={0}
                selectedPath={selectedPath}
                onFileSelect={onFileSelect}
                onToggle={handleToggle}
              />
            </div>
          )}
        </VirtualList>
      </div>
    )
  }

  return (
    <div className={cn('overflow-auto', className)}>
      {treeNodes.map((node) => (
        <TreeNodeItem
          key={node.entry.path}
          node={node}
          depth={0}
          selectedPath={selectedPath}
          onFileSelect={onFileSelect}
          onToggle={handleToggle}
        />
      ))}
    </div>
  )
}
