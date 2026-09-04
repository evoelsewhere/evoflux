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
 * - Virtual scrolling once the *visible* row count gets large
 *
 * Rows are flattened before rendering so virtualization measures one row per
 * line on screen. Virtualizing the nested nodes instead (one "row" per root
 * entry, each carrying its whole expanded subtree) sized every subtree to a
 * single row's height and clipped it.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { List as VirtualList } from 'react-window'
import {
  AlertCircle,
  ChevronRight,
  Loader2,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { tauriListDirectory, type DirEntry } from '@/api/tauri-workspace'
import { formatBytes } from '@/utils/format'
import { errorMessage } from '@/utils/errors'
import { FileTypeIcon, FolderTypeIcon } from './FileTypeIcon'
import {
  FileExplorerContextMenu,
  type FileExplorerEntry,
  type FileExplorerMenuActions,
} from './FileExplorerContextMenu'

/** Flattened rows above this count render through the virtual list. */
const VIRTUAL_SCROLL_THRESHOLD = 100
/** Height of one row, in px — must match the row styling below. */
const ROW_HEIGHT = 24
const DEPTH_INDENT = 16

// ── Types ────────────────────────────────────────────────────────────────────

type TreeRow =
  | { kind: 'entry'; key: string; depth: number; entry: DirEntry; isExpanded: boolean }
  | { kind: 'loading'; key: string; depth: number }
  | { kind: 'error'; key: string; depth: number; path: string; message: string }

/** Root listing for one request — either its entries or why they are missing. */
interface RootListing {
  key: string
  entries?: DirEntry[]
  error?: string
}

/** Lazily loaded directory listings for one request. */
interface DirCache {
  key: string
  children: Map<string, DirEntry[]>
  errors: Map<string, string>
}

const EMPTY_CHILDREN: ReadonlyMap<string, DirEntry[]> = new Map()
const EMPTY_ERRORS: ReadonlyMap<string, string> = new Map()

function emptyCache(key: string): DirCache {
  return { key, children: new Map(), errors: new Map() }
}

interface NativeFileTreeProps {
  /** Absolute path to workspace root */
  workspaceRoot: string
  /** Currently selected file path */
  selectedPath?: string | null
  /** Callback when a file is selected */
  onFileSelect?: (entry: DirEntry | null) => void
  /** Callback when a file is double-clicked */
  onFileOpen?: (entry: DirEntry) => void
  /** Right-click menu capabilities, built by the owning panel. */
  menuActions?: FileExplorerMenuActions
  /**
   * Bump to discard cached directory listings and re-read from disk — the
   * panel's Refresh button and its own file mutations both need this, since
   * native listings live here rather than in the query cache.
   */
  reloadKey?: number
  /** Optional className */
  className?: string
}

// ── Row rendering ────────────────────────────────────────────────────────────

function EntryRow({
  row,
  selectedPath,
  onFileSelect,
  onFileOpen,
  onToggle,
  menuActions,
}: {
  row: Extract<TreeRow, { kind: 'entry' }>
  selectedPath?: string | null
  onFileSelect?: (entry: DirEntry | null) => void
  onFileOpen?: (entry: DirEntry) => void
  onToggle: (path: string) => void
  menuActions?: FileExplorerMenuActions
}) {
  const { entry, depth, isExpanded } = row
  const isSelected = entry.path === selectedPath

  const handleClick = () => {
    if (entry.is_dir) onToggle(entry.path)
    else onFileSelect?.(isSelected ? null : entry)
  }

  const button = (
    <button
      type="button"
      onClick={handleClick}
      onDoubleClick={() => { if (!entry.is_dir) onFileOpen?.(entry) }}
      className={cn(
        'flex h-6 w-full items-center gap-1.5 rounded px-2 text-left text-xs transition-colors',
        isSelected
          ? 'bg-(--bg-key) text-(--color-accent)'
          : 'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)',
      )}
      style={{ paddingLeft: 8 + depth * DEPTH_INDENT }}
      title={entry.path}
    >
      {entry.is_dir ? (
        <>
          <span className="flex h-4 w-4 shrink-0 items-center justify-center">
            <ChevronRight
              size={12}
              className={cn('transition-transform', isExpanded && 'rotate-90')}
            />
          </span>
          <FolderTypeIcon open={isExpanded} size={16} />
        </>
      ) : (
        <>
          <span className="w-4 shrink-0" />
          <FileTypeIcon name={entry.name} mime={entry.mime} size={16} />
        </>
      )}
      <span className="min-w-0 flex-1 truncate font-mono">{entry.name}</span>
      {!entry.is_dir && (
        <span className="shrink-0 text-xs text-(--color-text-subtle)">
          {formatBytes(entry.size)}
        </span>
      )}
    </button>
  )

  if (!menuActions) return button

  const menuEntry: FileExplorerEntry = {
    path: entry.path,
    name: entry.name,
    isDirectory: entry.is_dir,
    size: entry.size,
    mtime: entry.mtime,
    mime: entry.mime,
  }
  return (
    <FileExplorerContextMenu entry={menuEntry} actions={menuActions}>
      {button}
    </FileExplorerContextMenu>
  )
}

function TreeRowView({
  row,
  selectedPath,
  onFileSelect,
  onFileOpen,
  onToggle,
  onRetry,
  menuActions,
}: {
  row: TreeRow
  selectedPath?: string | null
  onFileSelect?: (entry: DirEntry | null) => void
  onFileOpen?: (entry: DirEntry) => void
  onToggle: (path: string) => void
  onRetry: (path: string) => void
  menuActions?: FileExplorerMenuActions
}) {
  if (row.kind === 'loading') {
    return (
      <div
        className="flex h-6 items-center gap-1.5 px-2 text-xs text-(--color-text-subtle)"
        style={{ paddingLeft: 8 + row.depth * DEPTH_INDENT }}
      >
        <Loader2 size={12} className="animate-spin" />
        <span>Loading…</span>
      </div>
    )
  }

  if (row.kind === 'error') {
    return (
      <button
        type="button"
        onClick={() => onRetry(row.path)}
        title={row.message}
        className="flex h-6 w-full items-center gap-1.5 px-2 text-left text-xs text-(--color-error) hover:bg-(--bg-key)"
        style={{ paddingLeft: 8 + row.depth * DEPTH_INDENT }}
      >
        <AlertCircle size={12} className="shrink-0" />
        <span className="min-w-0 flex-1 truncate">{row.message}</span>
        <span className="shrink-0 text-(--color-text-subtle)">Retry</span>
      </button>
    )
  }

  return (
    <EntryRow
      row={row}
      selectedPath={selectedPath}
      onFileSelect={onFileSelect}
      onFileOpen={onFileOpen}
      onToggle={onToggle}
      menuActions={menuActions}
    />
  )
}

// ── Main Component ───────────────────────────────────────────────────────────

export function NativeFileTree({
  workspaceRoot,
  selectedPath,
  onFileSelect,
  onFileOpen,
  menuActions,
  reloadKey = 0,
  className,
}: NativeFileTreeProps) {
  // Both the root listing and the per-directory caches are stamped with the
  // request they belong to, so a reload invalidates them without an effect
  // that synchronously resets state (which would cascade renders).
  const requestKey = `${workspaceRoot}:${reloadKey}`
  const [root, setRoot] = useState<RootListing | null>(null)
  const [cache, setCache] = useState<DirCache>(() => emptyCache(''))
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set())

  const currentRoot = root?.key === requestKey ? root : null
  const currentCache = cache.key === requestKey ? cache : null
  const dirChildren = currentCache?.children ?? EMPTY_CHILDREN
  const dirErrors = currentCache?.errors ?? EMPTY_ERRORS
  const rootEntries = currentRoot?.entries ?? null
  const loading = currentRoot === null
  const error = currentRoot?.error ?? null

  const rememberChildren = useCallback((path: string, entries: DirEntry[]) => {
    setCache((prev) => {
      const base = prev.key === requestKey ? prev : emptyCache(requestKey)
      return {
        key: requestKey,
        children: new Map(base.children).set(path, entries),
        errors: base.errors,
      }
    })
  }, [requestKey])

  const rememberFailure = useCallback((path: string, message: string) => {
    setCache((prev) => {
      const base = prev.key === requestKey ? prev : emptyCache(requestKey)
      return {
        key: requestKey,
        children: base.children,
        errors: new Map(base.errors).set(path, message),
      }
    })
  }, [requestKey])

  // Load (or reload) the root directory.
  useEffect(() => {
    let cancelled = false

    tauriListDirectory(workspaceRoot, '')
      .then((result) => {
        if (!cancelled) setRoot({ key: requestKey, entries: result.entries })
      })
      .catch((reason: unknown) => {
        if (!cancelled) setRoot({ key: requestKey, error: errorMessage(reason) })
      })

    return () => { cancelled = true }
  }, [workspaceRoot, requestKey])

  // Fetch children for every expanded directory that has none yet. Doing this
  // here rather than inside the click handler means expansion state is the
  // single source of truth: a reload, a retry, and a click all converge on
  // the same fetch, and a failure is remembered instead of leaving the row
  // spinning forever.
  useEffect(() => {
    if (rootEntries === null) return
    const pending = [...expandedDirs].filter(
      (path) => !dirChildren.has(path) && !dirErrors.has(path),
    )
    if (pending.length === 0) return
    let cancelled = false

    for (const path of pending) {
      tauriListDirectory(workspaceRoot, path)
        .then((result) => {
          if (!cancelled) rememberChildren(path, result.entries)
        })
        .catch((reason: unknown) => {
          if (!cancelled) rememberFailure(path, errorMessage(reason))
        })
    }

    return () => { cancelled = true }
  }, [
    dirChildren,
    dirErrors,
    expandedDirs,
    rememberChildren,
    rememberFailure,
    rootEntries,
    workspaceRoot,
  ])

  const handleToggle = useCallback((dirPath: string) => {
    setExpandedDirs((prev) => {
      const next = new Set(prev)
      if (next.has(dirPath)) next.delete(dirPath)
      else next.add(dirPath)
      return next
    })
  }, [])

  const handleRetry = useCallback((dirPath: string) => {
    setCache((prev) => {
      if (prev.key !== requestKey || !prev.errors.has(dirPath)) return prev
      const errors = new Map(prev.errors)
      errors.delete(dirPath)
      return { key: prev.key, children: prev.children, errors }
    })
  }, [requestKey])

  // Flatten the open tree into one row per visible line.
  const rows = useMemo(() => {
    const flattened: TreeRow[] = []

    const walk = (entries: DirEntry[], depth: number) => {
      for (const entry of entries) {
        const isExpanded = entry.is_dir && expandedDirs.has(entry.path)
        flattened.push({ kind: 'entry', key: entry.path, depth, entry, isExpanded })
        if (!isExpanded) continue
        const children = dirChildren.get(entry.path)
        const failure = dirErrors.get(entry.path)
        if (children) {
          walk(children, depth + 1)
        } else if (failure) {
          flattened.push({
            kind: 'error',
            key: `${entry.path}:error`,
            depth: depth + 1,
            path: entry.path,
            message: failure,
          })
        } else {
          flattened.push({ kind: 'loading', key: `${entry.path}:loading`, depth: depth + 1 })
        }
      }
    }

    walk(rootEntries ?? [], 0)
    return flattened
  }, [rootEntries, expandedDirs, dirChildren, dirErrors])

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

  if (rows.length > VIRTUAL_SCROLL_THRESHOLD) {
    return (
      <div className={cn('min-h-0', className)}>
        <VirtualList
          className="h-full"
          defaultHeight={Math.min(600, rows.length * ROW_HEIGHT)}
          rowCount={rows.length}
          rowHeight={ROW_HEIGHT}
          rowProps={{}}
          rowComponent={({ index, style }) => (
            <div style={style}>
              <TreeRowView
                row={rows[index]}
                selectedPath={selectedPath}
                onFileSelect={onFileSelect}
                onFileOpen={onFileOpen}
                onToggle={handleToggle}
                onRetry={handleRetry}
                menuActions={menuActions}
              />
            </div>
          )}
        />
      </div>
    )
  }

  return (
    <div className={cn('overflow-auto', className)}>
      {rows.map((row) => (
        <TreeRowView
          key={row.key}
          row={row}
          selectedPath={selectedPath}
          onFileSelect={onFileSelect}
          onFileOpen={onFileOpen}
          onToggle={handleToggle}
          onRetry={handleRetry}
          menuActions={menuActions}
        />
      ))}
    </div>
  )
}
