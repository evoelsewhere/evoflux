/**
 * WorkspaceFilesPanel — docked side panel listing every file the agent has
 * written into the session workspace (``.evoflux/team/{sid}``).
 *
 * Layout: docked panel that shrinks the chat column (mirrors
 * ``CodingWorkspacePanel``) — a flex sibling of ``<main>``, not an overlay,
 * so opening it resizes the layout instead of covering it. Fixed-position
 * full-screen only below the ``md`` breakpoint (mobile). Inside, preview is
 * the primary surface and the resizable file tree is a collapsible right rail.
 * Images render inline via the ``/media/`` proxy (with lightbox on click).
 * Text/code files render as-is in a plain monospace view. Office documents
 * (.docx/.xlsx/.pptx) render via docx-preview / xlsx / pptx-renderer.
 * Everything else can be opened in the system's default desktop app.
 *
 * Data flow:
 *   - GET /api/team/{sid}/files      → listing (polled on open, invalidated
 *                                       by team store after write/edit/rm)
 *   - GET /api/team/{sid}/media/{p}  → file bytes (fetched by preview only
 *                                       when the user selects a text file;
 *                                       images use the URL directly as src)
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import {
  X,
  FileText,
  File as FileIcon,
  Folder,
  RefreshCw,
  Loader2,
  ExternalLink,
  Copy,
  Check,
  ArrowLeft,
  ChevronRight,
  Search,
  Upload,
  Edit2,
  RotateCcw,
  FolderOpen,
  Trash2,
  Pencil,
  FolderUp,
  MoreHorizontal,
  LocateFixed,
  PanelRightClose,
  PanelRightOpen,
} from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { cn } from '@/lib/utils'
import { workspaceMediaUrl, updateSessionWorkspace, uploadWorkspaceFiles, moveWorkspaceFile, deleteWorkspaceFile, browseWorkspaces } from '@/api/client'
import {
  isTauriAvailable,
  tauriOpenWorkspaceFile,
  tauriOpenWorkspaceRoot,
  tauriReadWorkspaceFile,
  tauriRevealWorkspacePath,
} from '@/api/tauri-workspace'
import { useWorkspaceFilesQuery } from '@/queries'
import { queryKeys } from '@/queries/keys'
import { useIsMobile } from '@/hooks/use-mobile'
import { useSessionFilesWatcher } from '@/hooks/useSessionFilesWatcher'
import { usePlatform } from '@/hooks/use-platform'
import { mediumHapticFeedback } from '@/lib/haptics'
import { formatBytes } from '@/utils/format'
import { MarkdownBlock } from '@/utils/markdown'
import { SidePanel } from './shell/SidePanel'
import { useUIStore } from '@/stores/useUIStore'
import { getWorkspacePanelLayout } from '@/lib/workspace-panel-layout'
import { ImageLightbox } from './ImageLightbox'
import { FileTypeIcon, FolderTypeIcon } from './FileTypeIcon'
import { DocxPreview, XlsxPreview, PptxPreview } from './workspace-office-preview'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from './ui/dropdown-menu'
import { openExternalUrl } from '@/lib/open-external'
import type { WorkspaceFileInfo } from '@/api/types'

// ── File-type helpers ─────────────────────────────────────────────────────────

// Extensions we preview as plain text. Other formats open in their desktop app.
const FILE_LONG_PRESS_MS = 520
const FILE_LONG_PRESS_MOVE_TOLERANCE = 10

const TEXT_EXTENSIONS = new Set([
  'txt', 'md', 'markdown', 'rst',
  'json', 'jsonl', 'ndjson', 'yaml', 'yml', 'toml', 'ini', 'env', 'gitignore',
  'csv', 'tsv', 'log',
  'py', 'ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs',
  'html', 'css', 'scss', 'sass',
  'sh', 'bash', 'zsh', 'fish',
  'rs', 'go', 'java', 'kt', 'c', 'cpp', 'h', 'hpp', 'rb', 'php', 'swift',
  'sql', 'xml', 'svg',
])

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'])
const DOCX_EXTENSIONS = new Set(['docx'])
const XLSX_EXTENSIONS = new Set(['xlsx'])
const PPTX_EXTENSIONS = new Set(['pptx'])

function extOf(name: string): string {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i + 1).toLowerCase() : ''
}

type FileKind = 'image' | 'text' | 'docx' | 'xlsx' | 'pptx' | 'binary'

function kindOf(file: WorkspaceFileInfo): FileKind {
  const ext = extOf(file.name)
  // SVG is both an image (for preview) and text — prefer the visual preview.
  if (IMAGE_EXTENSIONS.has(ext)) return 'image'
  if (file.mime.startsWith('image/')) return 'image'
  if (DOCX_EXTENSIONS.has(ext)) return 'docx'
  if (XLSX_EXTENSIONS.has(ext)) return 'xlsx'
  if (PPTX_EXTENSIONS.has(ext)) return 'pptx'
  if (!ext) return 'text'
  if (TEXT_EXTENSIONS.has(ext)) return 'text'
  if (file.mime.startsWith('text/')) return 'text'
  if (file.mime === 'application/json') return 'text'
  return 'binary'
}

// ── Resize constants ─────────────────────────────────────────────────────────

const PANEL_WIDTH_KEY = STORAGE_KEYS.panels.workspace
const TREE_WIDTH_KEY = STORAGE_KEYS.panels.workspaceTree
const TREE_VISIBILITY_KEY = STORAGE_KEYS.workspaceFiles.treeVisible
const TREE_WIDTH_MIN = 220
const TREE_WIDTH_DEFAULT = 280
const TREE_WIDTH_MAX = 380
const TREE_WIDTH_MAX_RATIO = 0.42

function readStoredWidth(key: string, fallback: number, min: number): number {
  try {
    const v = localStorage.getItem(key)
    return v ? Math.max(min, parseInt(v, 10)) : fallback
  } catch {
    return fallback
  }
}

function readStoredBoolean(key: string, fallback: boolean): boolean {
  try {
    const value = localStorage.getItem(key)
    return value === null ? fallback : value === 'true'
  } catch {
    return fallback
  }
}

// ── Tree data structure ───────────────────────────────────────────────────
//
// Builds a nested tree from the flat file listing so directories can be
// collapsed/expanded like VS Code's explorer.

interface TreeNode {
  name: string
  path: string
  children: Map<string, TreeNode>
  file?: WorkspaceFileInfo
}

function buildTree(files: WorkspaceFileInfo[]): TreeNode {
  const root: TreeNode = { name: '/', path: '', children: new Map() }
  for (const file of files) {
    const parts = file.path.split('/')
    let node = root
    parts.forEach((part, index) => {
      const path = parts.slice(0, index + 1).join('/')
      let child = node.children.get(part)
      if (!child) {
        child = { name: part, path, children: new Map() }
        node.children.set(part, child)
      }
      if (index === parts.length - 1) child.file = file
      node = child
    })
  }
  return root
}

/** Return the set of paths that should be visible when the given query is
 *  active.  A file matches when its path (case-insensitive) contains the
 *  query.  Ancestor directories of every matching file are also included so
 *  the tree stays connected. */
function matchingPaths(files: WorkspaceFileInfo[], query: string): Set<string> | null {
  if (!query.trim()) return null  // null = no filter active
  const q = query.toLowerCase()
  const matched = new Set<string>()
  for (const f of files) {
    if (f.path.toLowerCase().includes(q) || f.name.toLowerCase().includes(q)) {
      // Mark the file and every ancestor dir.
      const parts = f.path.split('/')
      for (let i = 1; i <= parts.length; i++) {
        matched.add(parts.slice(0, i).join('/'))
      }
    }
  }
  return matched
}

// ── Tree node ─────────────────────────────────────────────────────────────────

/** Recursive tree node — renders a folder row (with expand/collapse) or a
 *  file row.  ``depth`` controls left-padding indentation. */
function TreeNodeView({
  node,
  depth,
  selectedPath,
  workspaceRoot,
  onSelect,
  onOpen,
  onReveal,
  onRename,
  onDelete,
  visiblePaths,
  defaultOpen,
}: {
  node: TreeNode
  depth: number
  selectedPath: string | null
  workspaceRoot: string | null
  onSelect: (file: WorkspaceFileInfo) => void
  onOpen: (file: WorkspaceFileInfo) => void
  onReveal: (file: WorkspaceFileInfo) => void
  onRename: (file: WorkspaceFileInfo, newPath: string) => Promise<void>
  onDelete: (file: WorkspaceFileInfo) => Promise<void>
  visiblePaths: Set<string> | null
  defaultOpen: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const isDir = node.children.size > 0 && !node.file
  const isMobile = useIsMobile()
  const { isTauri, os } = usePlatform()
  const isTauriMobile = isTauri && (os === 'ios' || os === 'android')
  const [actionsPoint, setActionsPoint] = useState<{ x: number; y: number } | null>(null)
  const longPressTimerRef = useRef<number | null>(null)
  const longPressStartRef = useRef<{ x: number; y: number } | null>(null)
  const [isRenaming, setIsRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState('')
  const [isBusyRename, setIsBusyRename] = useState(false)
  const [isBusyDelete, setIsBusyDelete] = useState(false)
  const renameInputRef = useRef<HTMLInputElement>(null)

  // Keep folders open when a search filter is active so results are visible.
  const effectiveOpen = visiblePaths ? true : open

  // Sort: folders first, then alphabetical.
  const children = Array.from(node.children.values()).sort((a, b) => {
    const aDir = a.children.size > 0 && !a.file
    const bDir = b.children.size > 0 && !b.file
    if (aDir !== bDir) return aDir ? -1 : 1
    return a.name.localeCompare(b.name)
  })

  // When a filter is active, prune children that are not in visiblePaths.
  const filteredChildren = visiblePaths
    ? children.filter((child) => visiblePaths.has(child.path))
    : children

  const clearLongPress = () => {
    if (longPressTimerRef.current !== null) window.clearTimeout(longPressTimerRef.current)
    longPressTimerRef.current = null
    longPressStartRef.current = null
  }

  const copyPath = async () => {
    const relativePath = node.file!.path
    const fullPath = workspaceRoot
      ? `${workspaceRoot.replace(/[\\/]+$/, '')}/${relativePath}`
      : relativePath
    await navigator.clipboard.writeText(fullPath)
  }

  // If filtering and nothing matches under this node, hide the whole subtree.
  if (visiblePaths && !visiblePaths.has(node.path) && filteredChildren.length === 0) {
    return null
  }

  if (!isDir && node.file) {
    // ── File leaf ──────────────────────────────────────────────────────────
    const isSelected = node.file.path === selectedPath

    const commitRename = async () => {
      const trimmed = renameValue.trim()
      if (!trimmed || trimmed === node.name) { setIsRenaming(false); return }
      const dir = node.file!.path.includes('/')
        ? node.file!.path.slice(0, node.file!.path.lastIndexOf('/') + 1)
        : ''
      const newPath = dir + trimmed
      setIsBusyRename(true)
      try {
        await onRename(node.file!, newPath)
      } finally {
        setIsBusyRename(false)
        setIsRenaming(false)
      }
    }

    return (
      <>
        {isRenaming ? (
          <div
            className="flex items-center gap-1.5 rounded px-2 py-1"
            style={{ paddingLeft: 8 + depth * 12 }}
          >
            <FileTypeIcon name={node.file!.name} mime={node.file!.mime} />
            <input
              ref={renameInputRef}
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void commitRename()
                if (e.key === 'Escape') setIsRenaming(false)
              }}
              onBlur={() => void commitRename()}
              disabled={isBusyRename}
              className="flex-1 rounded border border-(--color-border) bg-(--color-surface) px-1 py-0 font-mono text-xs text-(--color-text) outline-none focus:border-(--focus-ring)"
              autoFocus
            />
            {isBusyRename && <Loader2 size={11} className="animate-spin shrink-0 text-(--color-text-muted)" />}
          </div>
        ) : (
        <button
          onClick={() => onSelect(node.file!)}
          onDoubleClick={() => onOpen(node.file!)}
          onContextMenu={(event) => {
            if (isTauriMobile) return
            event.preventDefault()
            setActionsPoint({ x: event.clientX, y: event.clientY })
          }}
          onPointerDown={(event) => {
            if (!isMobile || !isTauriMobile || event.pointerType === 'mouse') return
            longPressStartRef.current = { x: event.clientX, y: event.clientY }
            longPressTimerRef.current = window.setTimeout(() => {
              longPressTimerRef.current = null
              longPressStartRef.current = null
              mediumHapticFeedback()
              setActionsPoint({ x: event.clientX, y: event.clientY })
            }, FILE_LONG_PRESS_MS)
          }}
          onPointerMove={(event) => {
            const start = longPressStartRef.current
            if (!start) return
            if (
              Math.abs(event.clientX - start.x) > FILE_LONG_PRESS_MOVE_TOLERANCE ||
              Math.abs(event.clientY - start.y) > FILE_LONG_PRESS_MOVE_TOLERANCE
            ) {
              clearLongPress()
            }
          }}
          onPointerUp={clearLongPress}
          onPointerCancel={clearLongPress}
          onPointerLeave={clearLongPress}
          className={cn(
            'group flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-xs transition-colors',
            isSelected
              ? 'bg-(--bg-key) text-(--color-accent)'
              : 'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)',
          )}
          style={{ paddingLeft: 8 + depth * 12 }}
          title={node.file.path}
        >
          <FileTypeIcon name={node.file.name} mime={node.file.mime} />
          <span className="min-w-0 flex-1 truncate font-mono">{node.name}</span>
          <span className="shrink-0 text-xs text-(--color-text-subtle)">
            {formatBytes(node.file.size)}
          </span>
        </button>
        )}
        {actionsPoint && (
          <div
            className="fixed inset-0 z-(--z-lightbox)"
            onClick={() => setActionsPoint(null)}
            onContextMenu={(event) => {
              event.preventDefault()
              setActionsPoint(null)
            }}
          >
            <div
              role="menu"
              aria-label={`Actions for ${node.file!.name}`}
              className="fixed min-w-44 rounded-lg border border-(--color-border) bg-(--bg-card) p-1 text-sm text-(--color-text) shadow-xl"
              style={{ left: actionsPoint.x, top: actionsPoint.y }}
              onClick={(event) => event.stopPropagation()}
            >
              <button
                type="button"
                role="menuitem"
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
                onClick={() => {
                  setActionsPoint(null)
                  onOpen(node.file!)
                }}
              >
                <ExternalLink size={14} aria-hidden="true" />
                Open in default app
              </button>
              <button
                type="button"
                role="menuitem"
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
                onClick={() => {
                  setActionsPoint(null)
                  onSelect(node.file!)
                }}
              >
                <FileText size={14} aria-hidden="true" />
                Preview
              </button>
              <button
                type="button"
                role="menuitem"
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
                onClick={() => {
                  setActionsPoint(null)
                  void copyPath()
                }}
              >
                <Copy size={14} aria-hidden="true" />
                Copy full path
              </button>
              {isTauri && workspaceRoot && (
                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
                  onClick={() => {
                    setActionsPoint(null)
                    onReveal(node.file!)
                  }}
                >
                  <LocateFixed size={14} aria-hidden="true" />
                  {os === 'macos'
                    ? 'Reveal in Finder'
                    : os === 'windows'
                      ? 'Show in File Explorer'
                      : 'Show in folder'}
                </button>
              )}
              <button
                type="button"
                role="menuitem"
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
                onClick={() => {
                  setActionsPoint(null)
                  setRenameValue(node.file!.name)
                  setIsRenaming(true)
                }}
              >
                <Pencil size={14} aria-hidden="true" />
                Rename
              </button>
              <button
                type="button"
                role="menuitem"
                disabled={isBusyDelete}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-(--color-error) hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none disabled:opacity-50"
                onClick={() => {
                  setActionsPoint(null)
                  setIsBusyDelete(true)
                  void onDelete(node.file!).finally(() => setIsBusyDelete(false))
                }}
              >
                {isBusyDelete ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} aria-hidden="true" />}
                Delete
              </button>
            </div>
          </div>
        )}
      </>
    )
  }

  // ── Folder node ─────────────────────────────────────────────────────────
  if (!node.path) {
    // Root — render children directly without a folder row.
    return (
      <>
        {filteredChildren.map((child) => (
          <TreeNodeView
            key={child.path}
            node={child}
            depth={0}
            selectedPath={selectedPath}
            workspaceRoot={workspaceRoot}
            onSelect={onSelect}
            onOpen={onOpen}
            onReveal={onReveal}
            onRename={onRename}
            onDelete={onDelete}
            visiblePaths={visiblePaths}
            defaultOpen={defaultOpen}
          />
        ))}
      </>
    )
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-xs text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)"
        style={{ paddingLeft: 8 + depth * 12 }}
      >
        <ChevronRight
          size={12}
          className={cn('shrink-0 transition-transform', effectiveOpen && 'rotate-90')}
        />
        <FolderTypeIcon open={effectiveOpen} size={16} />
        <span className="min-w-0 flex-1 truncate font-mono">{node.name}</span>
      </button>
      {effectiveOpen &&
        filteredChildren.map((child) => (
          <TreeNodeView
            key={child.path}
            node={child}
            depth={depth + 1}
            selectedPath={selectedPath}
            workspaceRoot={workspaceRoot}
            onSelect={onSelect}
            onOpen={onOpen}
            onReveal={onReveal}
            onRename={onRename}
            onDelete={onDelete}
            visiblePaths={visiblePaths}
            defaultOpen={defaultOpen}
          />
        ))}
    </div>
  )
}

// ── Previews ──────────────────────────────────────────────────────────────────

function ImagePreview({ sessionId, file }: { sessionId: string; file: WorkspaceFileInfo }) {
  const [open, setOpen] = useState(false)
  const url = workspaceMediaUrl(sessionId, file.path)
  return (
    <>
      <div className="flex h-full items-center justify-center bg-(--bg-page) p-4">
        <img
          src={url}
          alt={file.name}
          onClick={() => setOpen(true)}
          className="max-h-full max-w-full cursor-zoom-in rounded border border-(--color-border) object-contain"
        />
      </div>
      <ImageLightbox
        src={url}
        alt={file.name}
        isOpen={open}
        onClose={() => setOpen(false)}
        allowDownload={false}
      />
    </>
  )
}

// Cap on bytes fetched for text preview — avoids loading a 50 MB log into
// the browser. Beyond this we show a notice and offer desktop opening.
const MAX_TEXT_PREVIEW_BYTES = 512 * 1024  // 512 KB

function TextPreview({ sessionId, file, workspaceRoot }: { sessionId: string; file: WorkspaceFileInfo; workspaceRoot?: string | null }) {
  const tooLarge = file.size > MAX_TEXT_PREVIEW_BYTES
  // Start in a loading state *unless* the file is too large — the effect is
  // skipped in that case and flipping loading=false there would trigger the
  // set-state-in-effect lint.  Keeping the initial state derived avoids it.
  const [content, setContent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(!tooLarge)

  useEffect(() => {
    if (tooLarge) return
    let cancelled = false

    async function loadFile() {
      try {
        let text: string
        // Native Rust path — no HTTP round-trip.
        if (isTauriAvailable() && workspaceRoot) {
          const b64 = await tauriReadWorkspaceFile(workspaceRoot, file.path)
          text = atob(b64)
        } else {
          // HTTP API fallback.
          const res = await fetch(workspaceMediaUrl(sessionId, file.path))
          if (!res.ok) throw new Error(`HTTP ${res.status}`)
          text = await res.text()
        }
        if (!cancelled) {
          setContent(text)
          setLoading(false)
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e))
          setLoading(false)
        }
      }
    }
    void loadFile()

    return () => {
      cancelled = true
    }
  }, [sessionId, file.path, tooLarge, workspaceRoot])

  if (tooLarge) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
        <FileText size={24} className="text-(--color-text-subtle)" />
        <p className="text-sm text-(--color-text-2)">File too large to preview</p>
        <p className="text-xs text-(--color-text-subtle)">
          {formatBytes(file.size)} — limit is {formatBytes(MAX_TEXT_PREVIEW_BYTES)}
        </p>
      </div>
    )
  }
  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-(--color-text-subtle)">
        <Loader2 size={16} className="animate-spin" />
      </div>
    )
  }
  if (error) {
    return (
      <div className="flex h-full items-center justify-center px-4 text-center text-xs text-(--color-error)">
        Failed to load: {error}
      </div>
    )
  }
  if (content === null) return null

  const ext = extOf(file.name)
  const isMarkdown = ext === 'md' || ext === 'markdown'
  // Code = any TEXT_EXTENSIONS entry that isn't a plain-prose or data format
  const PLAIN_TEXT_EXTS = new Set([
    'txt', 'log', 'csv', 'tsv', 'env', 'gitignore', 'ini', 'md', 'markdown', 'rst',
  ])
  const isCode = !isMarkdown && TEXT_EXTENSIONS.has(ext) && !PLAIN_TEXT_EXTS.has(ext)

  if (isMarkdown) {
    return (
      <div className="h-full overflow-auto px-6 py-4">
        <MarkdownBlock content={content} sessionId={sessionId} />
      </div>
    )
  }

  if (isCode) {
    // Wrap in a markdown code fence so rehype-highlight can apply syntax colouring.
    // MarkdownBlock's fixNestedFences will handle any backtick sequences inside.
    const fenced = '```' + ext + '\n' + content + '\n```'
    return (
      <div className="h-full overflow-auto p-2">
        <MarkdownBlock content={fenced} />
      </div>
    )
  }

  return (
    <pre className="h-full overflow-auto p-4 font-mono text-xs leading-relaxed text-(--color-text) whitespace-pre">
      {content}
    </pre>
  )
}

function BinaryPreview({ file }: { file: WorkspaceFileInfo }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <FileIcon size={28} className="text-(--color-text-subtle)" />
      <div>
        <p className="text-sm text-(--color-text-2)">No inline preview for this file type</p>
        <p className="mt-0.5 text-xs text-(--color-text-subtle)">
          {file.mime} · {formatBytes(file.size)}
        </p>
        <p className="mt-2 text-xs text-(--color-text-subtle)">
          Use Open to view it in the default app on this computer.
        </p>
      </div>
    </div>
  )
}

export function CopyContentsButton({
  sessionId,
  file,
  workspaceRoot,
}: {
  sessionId: string
  file: WorkspaceFileInfo
  workspaceRoot?: string | null
}) {
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const tooLarge = file.size > MAX_TEXT_PREVIEW_BYTES

  const handleCopy = async () => {
    if (busy || tooLarge) return
    setBusy(true)
    try {
      let text: string
      // Native Rust path — no HTTP round-trip.
      if (isTauriAvailable() && workspaceRoot) {
        const b64 = await tauriReadWorkspaceFile(workspaceRoot, file.path)
        text = atob(b64)
      } else {
        const res = await fetch(workspaceMediaUrl(sessionId, file.path))
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        text = await res.text()
      }
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Best-effort: opening the file in its desktop app remains available.
    } finally {
      setBusy(false)
    }
  }

  const title = tooLarge
    ? `File too large to copy (${formatBytes(file.size)} > ${formatBytes(MAX_TEXT_PREVIEW_BYTES)})`
    : copied
      ? 'Copied!'
      : 'Copy file contents'

  return (
    <button
      type="button"
      onClick={handleCopy}
      disabled={busy || tooLarge}
      title={title}
      aria-label={title}
      className="flex items-center gap-1 rounded px-2 py-1 text-xs text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2) disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-(--color-text-muted)"
    >
      {copied ? (
        <Check size={12} className="text-(--color-success)" />
      ) : busy ? (
        <Loader2 size={12} className="animate-spin" />
      ) : (
        <Copy size={12} />
      )}
    </button>
  )
}

function PreviewArea({
  sessionId,
  file,
  workspaceRoot,
  onOpen,
  onReveal,
  isDesktop,
}: {
  sessionId: string
  file: WorkspaceFileInfo
  workspaceRoot: string | null
  onOpen: (file: WorkspaceFileInfo) => void
  onReveal: (file: WorkspaceFileInfo) => void
  isDesktop: boolean
}) {
  const kind = kindOf(file)
  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-(--color-border) px-4 py-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <FileTypeIcon name={file.name} mime={file.mime} size={16} />
            <div className="truncate font-mono text-xs text-(--color-text)">{file.path}</div>
          </div>
          <div className="mt-0.5 text-xs text-(--color-text-subtle)">
            {formatBytes(file.size)} · {file.mime}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={() => onOpen(file)}
            className="flex items-center gap-1.5 rounded-md bg-(--bg-key) px-2.5 py-1 text-xs font-medium text-(--color-text) transition-colors hover:bg-(--bg-key-hover)"
            title="Open in default app"
          >
            <ExternalLink size={12} />
            Open
          </button>
          {isDesktop && workspaceRoot && (
            <button
              type="button"
              onClick={() => onReveal(file)}
              className="rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
              title="Show file in folder"
              aria-label="Show file in folder"
            >
              <LocateFixed size={12} />
            </button>
          )}
          {kind === 'text' && <CopyContentsButton sessionId={sessionId} file={file} workspaceRoot={workspaceRoot} />}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">
        {kind === 'image' ? (
          <ImagePreview sessionId={sessionId} file={file} />
        ) : kind === 'text' ? (
          <TextPreview sessionId={sessionId} file={file} workspaceRoot={workspaceRoot} />
        ) : kind === 'docx' ? (
          <DocxPreview sessionId={sessionId} file={file} />
        ) : kind === 'xlsx' ? (
          <XlsxPreview sessionId={sessionId} file={file} />
        ) : kind === 'pptx' ? (
          <PptxPreview sessionId={sessionId} file={file} />
        ) : (
          <BinaryPreview file={file} />
        )}
      </div>
    </div>
  )
}

// ── Empty states ──────────────────────────────────────────────────────────────

function EmptyState({ message, hint }: { message: string; hint?: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
      <FileText size={24} className="text-(--color-text-subtle)" />
      <p className="text-sm text-(--color-text-2)">{message}</p>
      {hint && <p className="max-w-xs text-xs text-(--color-text-subtle)">{hint}</p>}
    </div>
  )
}

// ── Main drawer ──────────────────────────────────────────────────────────────

interface WorkspaceFilesPanelProps {
  /** Controls drawer visibility.  Parent keeps the component mounted so
   *  framer-motion can play both the enter and exit animations. */
  open: boolean
  sessionId: string | null
  onClose: () => void
  embedded?: boolean
}

export function WorkspaceFilesPanel({ open, sessionId, onClose, embedded = false }: WorkspaceFilesPanelProps) {
  const isMobile = useIsMobile()
  const { isMacOverlay, isTauri } = usePlatform()
  const sidebarWidth = useUIStore((state) => state.sidebarWidth)
  const sidebarCollapsed = useUIStore((state) => state.sidebarCollapsed)
  const [viewportWidth, setViewportWidth] = useState(() =>
    typeof window === 'undefined' ? 1440 : window.innerWidth,
  )
  useEffect(() => {
    const handleResize = () => setViewportWidth(window.innerWidth)
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])
  const panelLayout = useMemo(
    () => getWorkspacePanelLayout({ viewportWidth, sidebarWidth, sidebarCollapsed, macOverlay: isMacOverlay }),
    [isMacOverlay, sidebarCollapsed, sidebarWidth, viewportWidth],
  )
  const isOverlay = panelLayout.mode === 'overlay'
  const { data, isLoading, isError, refetch, isFetching } = useWorkspaceFilesQuery(sessionId)
  const queryClient = useQueryClient()
  useSessionFilesWatcher(sessionId, data?.workspace_root)

  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  // Mobile: which pane is active — 'tree' (file list) or 'preview'
  const [mobilePane, setMobilePane] = useState<'tree' | 'preview'>('tree')
  const [desktopTreeVisible, setDesktopTreeVisible] = useState(() =>
    readStoredBoolean(TREE_VISIBILITY_KEY, true),
  )

  // Workspace picker state
  const [isPickerOpen, setIsPickerOpen] = useState(false)
  const [pickerPath, setPickerPath] = useState('')
  const [isPickerSaving, setIsPickerSaving] = useState(false)
  const [pickerError, setPickerError] = useState<string | null>(null)

  // Directory browser state (web fallback when not on Tauri desktop)
  const [browseDirs, setBrowseDirs] = useState<Array<{ name: string; path: string }>>([])
  const [browseParent, setBrowseParent] = useState<string | null>(null)
  const [browseLoading, setBrowseLoading] = useState(false)
  const [browseError, setBrowseError] = useState<string | null>(null)
  // Upload state
  const [isUploading, setIsUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dragCounterRef = useRef(0)

  // Outer panel width — docked, resizable from the left edge — is owned by
  // the surrounding <SidePanel> chrome (persisted under PANEL_WIDTH_KEY).
  // The preview owns the flexible space; the tree is a bounded right rail.
  // Clamp old saved widths so an earlier wide tree cannot starve the preview.
  const [treeWidth, setTreeWidth] = useState(() =>
    Math.min(
      TREE_WIDTH_MAX,
      readStoredWidth(TREE_WIDTH_KEY, TREE_WIDTH_DEFAULT, TREE_WIDTH_MIN),
    ),
  )
  const treePaneRef = useRef<HTMLElement>(null)
  const splitBodyRef = useRef<HTMLDivElement>(null)

  const startTreeResize = (e: React.PointerEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const startX = e.clientX
    // The rendered rail can be narrower than the persisted width when the
    // workbench is narrow, so resize from what the user actually sees.
    const startW = treePaneRef.current?.getBoundingClientRect().width ?? treeWidth
    const panelWidth = splitBodyRef.current?.getBoundingClientRect().width
      ?? (isOverlay ? viewportWidth : panelLayout.defaultWidth)
    const maxTW = Math.max(
      TREE_WIDTH_MIN,
      Math.min(TREE_WIDTH_MAX, Math.round(panelWidth * TREE_WIDTH_MAX_RATIO)),
    )
    let liveWidth = startW
    const onMove = (ev: PointerEvent) => {
      liveWidth = Math.max(
        TREE_WIDTH_MIN,
        Math.min(maxTW, startW + startX - ev.clientX),
      )
      // Keep pointer movement frame-perfect: update only the rail DOM while
      // dragging, then synchronize React/localStorage once on pointer-up.
      if (treePaneRef.current) treePaneRef.current.style.width = `${liveWidth}px`
    }
    const onUp = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      setTreeWidth(liveWidth)
      try { localStorage.setItem(TREE_WIDTH_KEY, String(liveWidth)) } catch { /* ignore */ }
    }
    document.body.style.cursor = 'ew-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp, { once: true })
    window.addEventListener('pointercancel', onUp, { once: true })
  }
  const resetTreeWidth = () => {
    setTreeWidth(TREE_WIDTH_DEFAULT)
    try { localStorage.setItem(TREE_WIDTH_KEY, String(TREE_WIDTH_DEFAULT)) } catch { /* ignore */ }
  }
  const searchInputRef = useRef<HTMLInputElement>(null)

  // Refresh on open so the list is fresh even if query was stale.
  useEffect(() => {
    if (open && sessionId) refetch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, sessionId])

  // Wrap ``data?.files ?? []`` in a memo so the ``files`` reference is stable
  // when the query returns the same cache entry — otherwise downstream
  // memoised derivations (``tree``) would recompute every render.
  const workspaceRoot = data?.workspace_root ?? null
  const files = useMemo<WorkspaceFileInfo[]>(() => data?.files ?? [], [data])
  const tree = useMemo(() => buildTree(files), [files])
  const visiblePaths = useMemo(() => matchingPaths(files, searchQuery), [files, searchQuery])

  // ── Workspace picker ────────────────────────────────────────────────────────

  const openPicker = async () => {
    setPickerError(null)
    setBrowseError(null)

    // On Tauri desktop: open native folder picker directly
    if (isTauri) {
      try {
        const { open } = await import('@tauri-apps/plugin-dialog')
        const selected = await open({ directory: true, multiple: false, title: 'Select workspace folder' })
        if (typeof selected === 'string') {
          // Apply immediately — no intermediate UI needed
          if (!sessionId) return
          setIsPickerSaving(true)
          try {
            const result = await updateSessionWorkspace(sessionId, selected)
            queryClient.setQueryData(queryKeys.team.files(sessionId), result)
          } catch (err) {
            setPickerError((err as Error).message ?? 'Failed to update workspace')
          } finally {
            setIsPickerSaving(false)
          }
        }
      } catch (err) {
        setPickerError(err instanceof Error ? err.message : 'Failed to open folder picker')
      }
      return
    }

    // On web: open inline directory browser
    setPickerPath(workspaceRoot ?? '')
    setBrowseDirs([])
    setBrowseParent(null)
    setIsPickerOpen(true)
    // Auto-load home directory
    void handleBrowse(null)
  }

  const handleBrowse = useCallback(async (path?: string | null) => {
    setBrowseLoading(true)
    setBrowseError(null)
    try {
      const result = await browseWorkspaces(path)
      setBrowseParent(result.parent)
      setBrowseDirs(result.directories)
    } catch (err) {
      setBrowseError(err instanceof Error ? err.message : 'Failed to browse directories')
    } finally {
      setBrowseLoading(false)
    }
  }, [])

  const handleSaveWorkspace = async (pathOverride?: string | null) => {
    if (!sessionId) return
    const newPath = pathOverride !== undefined ? pathOverride : pickerPath.trim() || null
    setIsPickerSaving(true)
    setPickerError(null)
    try {
      const result = await updateSessionWorkspace(sessionId, newPath)
      queryClient.setQueryData(queryKeys.team.files(sessionId), result)
      setIsPickerOpen(false)
    } catch (err) {
      setPickerError((err as Error).message ?? 'Failed to update workspace')
    } finally {
      setIsPickerSaving(false)
    }
  }

  // ── File upload ─────────────────────────────────────────────────────────────

  const handleUpload = useCallback(async (fileList: File[]) => {
    if (!sessionId || fileList.length === 0) return
    setIsUploading(true)
    setUploadError(null)
    try {
      const result = await uploadWorkspaceFiles(sessionId, fileList)
      queryClient.setQueryData(queryKeys.team.files(sessionId), result)
    } catch (err) {
      setUploadError((err as Error).message ?? 'Upload failed')
    } finally {
      setIsUploading(false)
    }
  }, [sessionId, queryClient])

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (files.length) void handleUpload(files)
    e.target.value = ''
  }

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault()
    dragCounterRef.current += 1
    if (e.dataTransfer.types.includes('Files')) setIsDragging(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    dragCounterRef.current -= 1
    if (dragCounterRef.current <= 0) { dragCounterRef.current = 0; setIsDragging(false) }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    dragCounterRef.current = 0
    setIsDragging(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length) void handleUpload(files)
  }

  // ── Rename / delete ─────────────────────────────────────────────────────────

  const handleRenameFile = useCallback(async (file: WorkspaceFileInfo, newPath: string) => {
    if (!sessionId) return
    try {
      const result = await moveWorkspaceFile(sessionId, file.path, newPath)
      queryClient.setQueryData(queryKeys.team.files(sessionId), result)
    } catch (err) {
      setUploadError((err as Error).message ?? 'Rename failed')
    }
  }, [sessionId, queryClient])

  const handleDeleteFile = useCallback(async (file: WorkspaceFileInfo) => {
    if (!sessionId) return
    try {
      const result = await deleteWorkspaceFile(sessionId, file.path)
      queryClient.setQueryData(queryKeys.team.files(sessionId), result)
      if (selectedPath === file.path) setSelectedPath(null)
    } catch (err) {
      setUploadError((err as Error).message ?? 'Delete failed')
    }
  }, [sessionId, queryClient, selectedPath])

  // ── Folder import ───────────────────────────────────────────────────────────
  const folderInputRef = useRef<HTMLInputElement>(null)

  const handleFolderInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (files.length) void handleUpload(files)
    e.target.value = ''
  }

  // Clear search when panel closes.
  useEffect(() => {
    if (!open) setSearchQuery('')
  }, [open])

  // Keep selection valid as the list churns — e.g. the selected file was deleted
  // by a new turn's rm tool call.  When the selection disappears, clear it.
  useEffect(() => {
    if (!selectedPath) return
    if (!files.some((f) => f.path === selectedPath)) {
      setSelectedPath(null)
      setMobilePane('tree')
    }
  }, [files, selectedPath])

  const selected = selectedPath ? files.find((f) => f.path === selectedPath) ?? null : null
  const workspaceName = useMemo(() => {
    if (!workspaceRoot) return 'Session workspace'
    const segments = workspaceRoot.split(/[\\/]/).filter(Boolean)
    const folderName = segments.at(-1) ?? workspaceRoot
    return folderName === sessionId ? 'Session workspace' : folderName
  }, [sessionId, workspaceRoot])

  const handleOpenFile = useCallback(async (file: WorkspaceFileInfo) => {
    setUploadError(null)
    try {
      if (isTauri && workspaceRoot) {
        await tauriOpenWorkspaceFile(workspaceRoot, file.path)
        return
      }
      if (sessionId) {
        await openExternalUrl(workspaceMediaUrl(sessionId, file.path))
      }
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Failed to open file')
    }
  }, [isTauri, sessionId, workspaceRoot])

  const handleOpenWorkspace = useCallback(async () => {
    if (!isTauri || !workspaceRoot) return
    setUploadError(null)
    try {
      await tauriOpenWorkspaceRoot(workspaceRoot)
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Failed to open workspace')
    }
  }, [isTauri, workspaceRoot])

  const handleRevealFile = useCallback(async (file: WorkspaceFileInfo) => {
    if (!isTauri || !workspaceRoot) return
    setUploadError(null)
    try {
      await tauriRevealWorkspacePath(workspaceRoot, file.path)
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Failed to show file in folder')
    }
  }, [isTauri, workspaceRoot])

  const handleRevealWorkspace = useCallback(async () => {
    if (!isTauri || !workspaceRoot) return
    setUploadError(null)
    try {
      await tauriRevealWorkspacePath(workspaceRoot)
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Failed to show workspace in folder')
    }
  }, [isTauri, workspaceRoot])

  const handleSelectFile = (f: WorkspaceFileInfo) => {
    setSelectedPath(f.path)
    if (isMobile) setMobilePane('preview')
  }

  const handleBackToTree = () => {
    setMobilePane('tree')
  }

  const toggleDesktopTree = () => {
    setDesktopTreeVisible((visible) => {
      const next = !visible
      try { localStorage.setItem(TREE_VISIBILITY_KEY, String(next)) } catch { /* ignore */ }
      return next
    })
  }

  // On mobile, tree pane and preview pane are mutually exclusive full-width views.
  const showTree = isMobile ? mobilePane === 'tree' : desktopTreeVisible
  const showPreview = !isMobile || mobilePane === 'preview'

  // Ctrl+F focuses the search input when the tree pane is visible.
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'f' && showTree) {
        e.preventDefault()
        searchInputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, showTree])

  if (!open) return null

  return (
    <SidePanel
      storageKey={PANEL_WIDTH_KEY}
      defaultWidth={panelLayout.defaultWidth}
      minWidth={panelLayout.minWidth}
      maxWidth={panelLayout.maxWidth}
      mobileOverlay
      mobile={isMobile}
      forceOverlay={isOverlay}
      fillParent={embedded}
      ariaLabel="Workspace files"
      className="bg-(--bg-card)"
    >
      {/* Header */}
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-(--color-border) px-3 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {/* Mobile back button — only shown in preview pane */}
          {isMobile && mobilePane === 'preview' && (
            <button
              onClick={handleBackToTree}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
              aria-label="Back to file list"
            >
              <ArrowLeft size={14} />
            </button>
          )}
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-(--color-text)">Files</h2>
            <p className="truncate text-xs text-(--color-text-subtle)">
              {isMobile && mobilePane === 'preview' && selected
                ? selected.name
                : <>{workspaceName}{data?.truncated ? ' · list truncated' : ''}</>
              }
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {isTauri && workspaceRoot && (
            <button
              type="button"
              onClick={() => void handleOpenWorkspace()}
              title="Open workspace folder"
              className="flex items-center gap-1.5 rounded-md bg-(--bg-key) px-2.5 py-1.5 text-xs font-medium text-(--color-text) transition-colors hover:bg-(--bg-key-hover)"
            >
              <FolderOpen size={14} />
              <span className="hidden xl:inline">Open folder</span>
            </button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger
              disabled={!sessionId}
              className="rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-50"
              title="Workspace actions"
              aria-label="Workspace actions"
            >
              {isUploading ? <Loader2 size={14} className="animate-spin" /> : <MoreHorizontal size={14} />}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuItem
                disabled={isUploading}
                onClick={() => fileInputRef.current?.click()}
              >
                <Upload size={14} />
                Import files
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={isUploading}
                onClick={() => folderInputRef.current?.click()}
              >
                <FolderUp size={14} />
                Import folder
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => void openPicker()}>
                <Edit2 size={14} />
                Change workspace
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <button
            onClick={() => refetch()}
            disabled={!sessionId || isFetching}
            className="rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-50"
            title="Refresh"
            aria-label="Refresh"
          >
            <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
          </button>
          {!isMobile && (
            <button
              type="button"
              onClick={toggleDesktopTree}
              className={cn(
                'rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)',
                showTree && 'bg-(--bg-key) text-(--color-text)',
              )}
              title={showTree ? 'Hide file tree' : 'Show file tree'}
              aria-label={showTree ? 'Hide file tree' : 'Show file tree'}
              aria-pressed={showTree}
            >
              {showTree ? <PanelRightClose size={15} /> : <PanelRightOpen size={15} />}
            </button>
          )}
          <button
            onClick={onClose}
            className="rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            title="Close"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>
      </header>

      {/* Workspace path bar + inline picker */}
      {sessionId && (
        <div className="shrink-0 border-b border-(--color-border)">
          <div className="flex items-center gap-2 px-3 py-2">
            <button
              type="button"
              onClick={() => void handleRevealWorkspace()}
              disabled={!isTauri || !workspaceRoot}
              className="flex min-w-0 flex-1 items-center gap-2 rounded-md text-left disabled:cursor-default"
              title={isTauri ? 'Show workspace in folder' : workspaceRoot ?? undefined}
            >
              <FolderOpen size={14} className="shrink-0 text-(--color-text-muted)" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium text-(--color-text-2)">
                  {workspaceName}
                </span>
                <span className="block truncate font-mono text-xs text-(--color-text-subtle)">
                  {workspaceRoot ?? 'Session sandbox (default)'}
                </span>
              </span>
              {isTauri && workspaceRoot && (
                <LocateFixed size={12} className="shrink-0 text-(--color-text-subtle)" />
              )}
            </button>
            <button
              onClick={openPicker}
              className={cn(
                'shrink-0 rounded px-2 py-0.5 text-xs text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)',
                isPickerOpen && 'bg-(--bg-key) text-(--color-text)',
              )}
              title="Change workspace folder"
              aria-label="Change workspace folder"
            >
              <Edit2 size={11} className="inline-block" />
            </button>
          </div>
          {isPickerOpen && (
            <div className="flex flex-col gap-2 border-t border-(--color-border) bg-(--bg-page) px-3 py-2">
              {/* Path input — type or paste a path manually */}
              <input
                type="text"
                value={pickerPath}
                onChange={(e) => setPickerPath(e.target.value)}
                placeholder="Type or browse to select a folder"
                className="w-full rounded border border-(--color-border) bg-(--color-surface) px-2 py-1.5 font-mono text-xs text-(--color-text) outline-none focus:border-(--focus-ring) placeholder:text-(--color-text-subtle)"
                onKeyDown={(e) => { if (e.key === 'Enter') void handleSaveWorkspace(); if (e.key === 'Escape') setIsPickerOpen(false) }}
              />
              {/* Directory browser — click a folder to select it */}
              <div className="max-h-48 overflow-y-auto rounded border border-(--color-border) bg-(--color-surface)">
                {browseLoading && (
                  <div className="flex items-center justify-center gap-2 py-3 text-xs text-(--color-text-muted)">
                    <Loader2 size={12} className="animate-spin" /> Loading…
                  </div>
                )}
                {!browseLoading && browseParent && (
                  <button
                    onClick={() => void handleBrowse(browseParent)}
                    className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-(--color-text-muted) hover:bg-(--bg-key)"
                  >
                    <FolderUp size={11} />
                    ..
                  </button>
                )}
                {!browseLoading && browseDirs.map((dir) => (
                  <button
                    key={dir.path}
                    onClick={() => setPickerPath(dir.path)}
                    className={cn(
                      'flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs transition-colors hover:bg-(--bg-key)',
                      pickerPath === dir.path ? 'text-(--color-accent) font-medium bg-(--bg-key)' : 'text-(--color-text)',
                    )}
                  >
                    <Folder size={11} className="shrink-0 text-(--color-text-muted)" />
                    <span className="truncate">{dir.name}</span>
                  </button>
                ))}
                {!browseLoading && browseDirs.length === 0 && !browseParent && (
                  <p className="px-2 py-3 text-center text-xs text-(--color-text-muted)">No subdirectories</p>
                )}
              </div>
              {browseError && (
                <p className="text-xs text-(--color-error)">{browseError}</p>
              )}
              {pickerError && (
                <p className="text-xs text-(--color-error)">{pickerError}</p>
              )}
              <div className="flex items-center gap-1.5">
                <button
                  onClick={() => void handleSaveWorkspace()}
                  disabled={isPickerSaving || !pickerPath.trim()}
                  className="rounded bg-(--color-accent) px-3 py-1 text-xs font-medium text-(--color-text-on-accent) transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  {isPickerSaving ? 'Applying…' : 'Select'}
                </button>
                <button
                  onClick={() => void handleSaveWorkspace(null)}
                  disabled={isPickerSaving}
                  className="flex items-center gap-1 rounded px-2 py-1 text-xs text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-50"
                  title="Reset to session sandbox"
                >
                  <RotateCcw size={11} />
                  Reset
                </button>
                <button
                  onClick={() => setIsPickerOpen(false)}
                  className="ml-auto rounded px-2 py-1 text-xs text-(--color-text-muted) transition-colors hover:bg-(--bg-key)"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
          {uploadError && (
            <div className="flex items-center justify-between border-t border-(--color-border) bg-(--bg-page) px-3 py-1.5">
              <span className="text-xs text-(--color-error)">{uploadError}</span>
              <button onClick={() => setUploadError(null)} className="text-(--color-text-muted) hover:text-(--color-text)"><X size={12} /></button>
            </div>
          )}
        </div>
      )}

      {/* Body: preview-first split (desktop) / master-detail (mobile) */}
      <div ref={splitBodyRef} className="flex min-h-0 flex-1 overflow-hidden">
        {/* Tree — a collapsible right rail on desktop, full-width on mobile. */}
        {showTree && (
          <nav
            ref={treePaneRef}
            className={cn(
              'relative order-3 flex flex-col overflow-hidden',
              isMobile ? 'w-full' : 'shrink-0',
            )}
            style={!isMobile
              ? {
                  width: `min(${treeWidth}px, ${TREE_WIDTH_MAX_RATIO * 100}%)`,
                  minWidth: TREE_WIDTH_MIN,
                }
              : undefined}
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
          >
            {isDragging && (
              <div className="pointer-events-none absolute inset-0 z-(--z-panel) flex flex-col items-center justify-center gap-2 rounded border-2 border-dashed border-(--color-accent) bg-(--color-accent)/8">
                <Upload size={22} className="text-(--color-accent)" />
                <span className="text-xs font-medium text-(--color-accent)">Drop to import</span>
              </div>
            )}
            {/* Search bar */}
            {sessionId && files.length > 0 && (
              <div className="shrink-0 border-b border-(--color-border) px-2 py-1.5">
                <div className="flex items-center gap-1.5 rounded-md border border-(--color-border) bg-(--bg-page) px-2 py-1">
                  <Search size={12} className="shrink-0 text-(--color-text-subtle)" />
                  <input
                    ref={searchInputRef}
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search files…"
                    className="w-full bg-transparent text-xs text-(--color-text) outline-none placeholder:text-(--color-text-subtle)"
                  />
                  {searchQuery && (
                    <button
                      type="button"
                      onClick={() => setSearchQuery('')}
                      className="shrink-0 rounded p-0.5 text-(--color-text-subtle) hover:text-(--color-text)"
                      aria-label="Clear search"
                    >
                      <X size={10} />
                    </button>
                  )}
                </div>
              </div>
            )}
            <div className="flex-1 overflow-y-auto px-2 py-3">
              {!sessionId ? (
                <p className="px-2 py-4 text-xs italic text-(--color-text-subtle)">
                  No active session.
                </p>
              ) : isLoading ? (
                <div className="px-2 py-6 text-center text-xs text-(--color-text-subtle)">
                  <Loader2 size={14} className="mx-auto animate-spin" />
                </div>
              ) : isError ? (
                <p className="px-2 py-4 text-xs text-(--color-error)">
                  Failed to load workspace files
                </p>
              ) : files.length === 0 ? (
                <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
                  <FolderOpen size={22} className="text-(--color-text-subtle)" />
                  <p className="text-xs font-medium text-(--color-text-2)">Workspace is empty</p>
                  <p className="max-w-44 text-xs text-(--color-text-subtle)">
                    Files created by the agent appear here automatically.
                  </p>
                </div>
              ) : visiblePaths && visiblePaths.size === 0 ? (
                <p className="px-2 py-4 text-xs italic text-(--color-text-subtle)">
                  No files match "{searchQuery}"
                </p>
              ) : (
                <TreeNodeView
                  node={tree}
                  depth={0}
                  selectedPath={selectedPath}
                  workspaceRoot={workspaceRoot}
                  onSelect={handleSelectFile}
                  onOpen={(file) => void handleOpenFile(file)}
                  onReveal={(file) => void handleRevealFile(file)}
                  onRename={handleRenameFile}
                  onDelete={handleDeleteFile}
                  visiblePaths={visiblePaths}
                  defaultOpen
                />
              )}
            </div>
          </nav>
        )}

        {/* Tree/preview drag divider — desktop only */}
        {!isMobile && showTree && showPreview && (
          <div
            className="relative order-2 w-px shrink-0 cursor-ew-resize bg-(--color-border) transition-colors hover:bg-(--color-accent)/40"
            onPointerDown={startTreeResize}
            onDoubleClick={resetTreeWidth}
            title="Drag to resize · double-click to reset"
          />
        )}

        {/* Preview — always receives the primary flexible surface. */}
        {showPreview && (
          <div className="order-1 min-w-0 flex-1">
            {selected && sessionId ? (
              <PreviewArea
                key={selected.path}
                sessionId={sessionId}
                file={selected}
                workspaceRoot={workspaceRoot}
                onOpen={(file) => void handleOpenFile(file)}
                onReveal={(file) => void handleRevealFile(file)}
                isDesktop={isTauri}
              />
            ) : (
              <EmptyState
                message="Select a file"
                hint={isTauri
                  ? 'Single-click to preview. Double-click to open with the default app.'
                  : 'Single-click to preview. Double-click opens the debug media URL.'}
              />
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="shrink-0 border-t border-(--color-border) px-4 py-2 text-xs text-(--color-text-muted) pb-safe">
        {files.length > 0 && (
          <span>
            {visiblePaths
              ? `${Array.from(visiblePaths).filter((p) => files.some((f) => f.path === p)).length} of ${files.length} file${files.length === 1 ? '' : 's'}`
              : `${files.length} file${files.length === 1 ? '' : 's'}`
            }
            {' · '}
          </span>
        )}
        {isMobile ? 'Tap a file to preview' : 'Double-click a file to open it'}
      </div>

      {/* Hidden file input for upload button */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        aria-hidden="true"
        onChange={handleFileInput}
      />
      {/* Hidden folder input for import folder button */}
      <input
        ref={folderInputRef}
        type="file"
        multiple
        // @ts-expect-error webkitdirectory is not in TS types
        webkitdirectory=""
        className="hidden"
        aria-hidden="true"
        onChange={handleFolderInput}
      />
    </SidePanel>
  )
}
