/**
 * WorkspaceFilesPanel — docked side panel listing every file the agent has
 * written into the session workspace (``.EvoFlux/team/{sid}``).
 *
 * Layout: docked panel that shrinks the chat column (mirrors
 * ``CodingWorkspacePanel``) — a flex sibling of ``<main>``, not an overlay,
 * so opening it resizes the layout instead of covering it. Fixed-position
 * full-screen only below the ``md`` breakpoint (mobile). Inside, a two-pane
 * split — tree grouped by directory on the left, preview on the right.
 * Images render inline via the ``/media/`` proxy (with lightbox on click).
 * Text/code files render as-is in a plain monospace view. Office documents
 * (.docx/.xlsx/.pptx) render via docx-preview / xlsx / pptx-renderer.
 * Everything else shows a "Download" fallback.
 *
 * Data flow:
 *   - GET /api/team/{sid}/files      → listing (polled on open, invalidated
 *                                       by team store after write/edit/rm)
 *   - GET /api/team/{sid}/media/{p}  → file bytes (fetched by preview only
 *                                       when the user selects a text file;
 *                                       images use the URL directly as src)
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import {
  X,
  FileText,
  FileImage,
  FileCode,
  FileSpreadsheet,
  Presentation as PresentationIcon,
  File as FileIcon,
  Folder,
  Download,
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
} from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { cn } from '@/lib/utils'
import { workspaceMediaUrl, updateSessionWorkspace, uploadWorkspaceFiles, moveWorkspaceFile, deleteWorkspaceFile, browseWorkspaces } from '@/api/client'
import { isTauriAvailable, tauriReadWorkspaceFile } from '@/api/tauri-workspace'
import { downloadWorkspaceFile } from '@/lib/workspace-download'
import { useWorkspaceFilesQuery } from '@/queries'
import { queryKeys } from '@/queries/keys'
import { useIsMobile } from '@/hooks/use-mobile'
import { useSessionFilesWatcher } from '@/hooks/useSessionFilesWatcher'
import { useResizableWidth } from '@/hooks/use-resizable-width'
import { useReducedMotion } from '@/hooks/useReducedMotion'
import { usePlatform } from '@/hooks/use-platform'
import { mediumHapticFeedback } from '@/lib/haptics'
import { formatBytes } from '@/utils/format'
import { MarkdownBlock } from '@/utils/markdown'
import { ImageLightbox } from './ImageLightbox'
import { DocxPreview, XlsxPreview, PptxPreview } from './workspace-office-preview'
import type { WorkspaceFileInfo } from '@/api/types'

// ── File-type helpers ─────────────────────────────────────────────────────────

// Extensions we preview as plain text.  Anything else falls back to "Download".
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
const XLSX_EXTENSIONS = new Set(['xlsx', 'xlsm'])
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

function FileTypeIcon({ file, size = 12 }: { file: WorkspaceFileInfo; size?: number }) {
  const kind = kindOf(file)
  const cls = 'shrink-0 text-(--color-text-muted)'
  if (kind === 'image') return <FileImage size={size} className={cls} />
  if (kind === 'xlsx') return <FileSpreadsheet size={size} className={cls} />
  if (kind === 'pptx') return <PresentationIcon size={size} className={cls} />
  if (kind === 'docx') return <FileText size={size} className={cls} />
  if (kind === 'text') {
    // Code files get the code icon; plain text/markdown use the document icon.
    const ext = extOf(file.name)
    const isCode = ext && !['txt', 'md', 'markdown', 'rst', 'log', 'csv', 'tsv'].includes(ext)
    return isCode ? <FileCode size={size} className={cls} /> : <FileText size={size} className={cls} />
  }
  return <FileIcon size={size} className={cls} />
}

function VscodeIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#007ACC" d="M23.15 2.587L18.21.21a1.494 1.494 0 0 0-1.705.29l-9.46 8.63-4.12-3.128a.999.999 0 0 0-1.276.057L.327 7.261A1 1 0 0 0 .326 8.74L3.899 12 .326 15.26a1 1 0 0 0 .001 1.479L1.65 17.94a.999.999 0 0 0 1.276.057l4.12-3.128 9.46 8.63a1.492 1.492 0 0 0 1.704.29l4.942-2.377A1.5 1.5 0 0 0 24 19.881V4.099a1.5 1.5 0 0 0-.85-1.512zm-5.146 14.861L10.826 12l7.178-5.448v10.896z" />
    </svg>
  )
}

function vscodeWorkspaceUrl(workspaceRoot: string): string {
  // vscode://file/{folder} opens the folder as a workspace in VS Code.
  // Convert backslashes to forward slashes for Windows paths.
  const root = workspaceRoot.replace(/\\/g, '/')
  return `vscode://file/${root}`
}

// ── Resize constants ─────────────────────────────────────────────────────────

const PANEL_WIDTH_KEY = 'workspace-panel-width'
const TREE_WIDTH_KEY = 'workspace-tree-width'
const PANEL_WIDTH_MIN = 320
const TREE_WIDTH_MIN = 160
const TREE_WIDTH_MAX_RATIO = 0.55

function readStoredWidth(key: string, fallback: number, min: number): number {
  try {
    const v = localStorage.getItem(key)
    return v ? Math.max(min, parseInt(v, 10)) : fallback
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
  sessionId,
  workspaceRoot,
  onSelect,
  onRename,
  onDelete,
  visiblePaths,
  defaultOpen,
}: {
  node: TreeNode
  depth: number
  selectedPath: string | null
  sessionId: string
  workspaceRoot: string | null
  onSelect: (file: WorkspaceFileInfo) => void
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
    await navigator.clipboard.writeText(node.file!.path)
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
            <FileTypeIcon file={node.file!} />
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
          <FileTypeIcon file={node.file} />
          <span className="min-w-0 flex-1 truncate font-mono">{node.name}</span>
          <span className="shrink-0 text-xs text-(--color-text-subtle)">
            {formatBytes(node.file.size)}
          </span>
        </button>
        )}
        {actionsPoint && (
          <div
            className="fixed inset-0 z-[70]"
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
                Copy path
              </button>
              <button
                type="button"
                role="menuitem"
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
                onClick={() => {
                  setActionsPoint(null)
                  void downloadWorkspaceFile(sessionId, node.file!)
                }}
              >
                <Download size={14} aria-hidden="true" />
                Download
              </button>
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
              {workspaceRoot && (
                <a
                  href={vscodeWorkspaceUrl(workspaceRoot)}
                  role="menuitem"
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
                  onClick={() => setActionsPoint(null)}
                >
                  <VscodeIcon size={14} />
                  Open in VS Code
                </a>
              )}
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
            sessionId={sessionId}
            workspaceRoot={workspaceRoot}
            onSelect={onSelect}
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
        <Folder size={12} className="shrink-0 text-(--color-accent)" />
        <span className="min-w-0 flex-1 truncate font-mono">{node.name}</span>
      </button>
      {effectiveOpen &&
        filteredChildren.map((child) => (
          <TreeNodeView
            key={child.path}
            node={child}
            depth={depth + 1}
            selectedPath={selectedPath}
            sessionId={sessionId}
            workspaceRoot={workspaceRoot}
            onSelect={onSelect}
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
      <ImageLightbox src={url} alt={file.name} isOpen={open} onClose={() => setOpen(false)} />
    </>
  )
}

// Cap on bytes fetched for text preview — avoids loading a 50 MB log into
// the browser.  Beyond this we show a notice + download button.
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

function BinaryPreview({ sessionId, file }: { sessionId: string; file: WorkspaceFileInfo }) {
  const url = workspaceMediaUrl(sessionId, file.path)
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <FileIcon size={28} className="text-(--color-text-subtle)" />
      <div>
        <p className="text-sm text-(--color-text-2)">No inline preview for this file type</p>
        <p className="mt-0.5 text-xs text-(--color-text-subtle)">
          {file.mime} · {formatBytes(file.size)}
        </p>
      </div>
      <div className="flex items-center gap-2">
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 rounded-md bg-(--bg-key) px-3 py-1.5 text-xs text-(--color-accent) transition-colors hover:bg-(--bg-key)"
        >
          <ExternalLink size={12} /> Open in new tab
        </a>
        <DownloadWorkspaceFileButton
          sessionId={sessionId}
          file={file}
          className="flex items-center gap-1.5 rounded-md border border-(--color-border) px-3 py-1.5 text-xs text-(--color-text-2) transition-colors hover:border-(--color-border-strong)"
        >
          <Download size={12} /> Download
        </DownloadWorkspaceFileButton>
      </div>
    </div>
  )
}

export function DownloadWorkspaceFileButton({
  sessionId,
  file,
  className,
  children,
}: {
  sessionId: string
  file: WorkspaceFileInfo
  className?: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={() => void downloadWorkspaceFile(sessionId, file)}
      className={className}
      title="Download"
      aria-label="Download"
    >
      {children}
    </button>
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
      // Swallow — the button is best-effort.  Failure is rare (clipboard
      // permission denied, or the media proxy returned non-2xx) and the user
      // can fall back to Download.
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
}: {
  sessionId: string
  file: WorkspaceFileInfo
  workspaceRoot: string | null
}) {
  const kind = kindOf(file)
  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-(--color-border) px-4 py-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <FileTypeIcon file={file} size={13} />
            <div className="truncate font-mono text-xs text-(--color-text)">{file.path}</div>
          </div>
          <div className="mt-0.5 text-xs text-(--color-text-subtle)">
            {formatBytes(file.size)} · {file.mime}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <DownloadWorkspaceFileButton
            sessionId={sessionId}
            file={file}
            className="flex items-center gap-1 rounded px-2 py-1 text-xs text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
          >
            <Download size={12} />
          </DownloadWorkspaceFileButton>
          {kind === 'text' && <CopyContentsButton sessionId={sessionId} file={file} workspaceRoot={workspaceRoot} />}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">
        {kind === 'image' ? (
          <ImagePreview sessionId={sessionId} file={file} />
        ) : kind === 'text' ? (
          <TextPreview sessionId={sessionId} file={file} workspaceRoot={workspaceRoot} />
        ) : kind === 'docx' ? (
          <DocxPreview sessionId={sessionId} file={file} workspaceRoot={workspaceRoot} />
        ) : kind === 'xlsx' ? (
          <XlsxPreview sessionId={sessionId} file={file} workspaceRoot={workspaceRoot} />
        ) : kind === 'pptx' ? (
          <PptxPreview sessionId={sessionId} file={file} workspaceRoot={workspaceRoot} />
        ) : (
          <BinaryPreview sessionId={sessionId} file={file} />
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
}

export function WorkspaceFilesPanel({ open, sessionId, onClose }: WorkspaceFilesPanelProps) {
  const isMobile = useIsMobile()
  const { isMacOverlay } = usePlatform()
  const { data, isLoading, isError, refetch, isFetching } = useWorkspaceFilesQuery(sessionId)
  const prefersReducedMotion = useReducedMotion()
  const queryClient = useQueryClient()
  useSessionFilesWatcher(sessionId, data?.workspace_root)

  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  // Mobile: which pane is active — 'tree' (file list) or 'preview'
  const [mobilePane, setMobilePane] = useState<'tree' | 'preview'>('tree')

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
  const { isTauri } = usePlatform()

  // Upload state
  const [isUploading, setIsUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dragCounterRef = useRef(0)

  // Outer panel width — docked, resizable from the left edge (mirrors
  // CodingWorkspacePanel). Tree/preview split width is a separate, internal
  // resize handled by its own hand-rolled drag below.
  const resizablePanel = useResizableWidth({
    storageKey: PANEL_WIDTH_KEY,
    defaultWidth: Math.min(960, Math.round((typeof window === 'undefined' ? 1280 : window.innerWidth) * 0.6)),
    minWidth: PANEL_WIDTH_MIN,
    maxWidth: Math.round((typeof window === 'undefined' ? 1280 : window.innerWidth) * 0.95),
    edge: 'left',
    disabled: isMobile,
  })
  const panelWidth = resizablePanel.width

  const [treeWidth, setTreeWidth] = useState(() =>
    readStoredWidth(TREE_WIDTH_KEY, 260, TREE_WIDTH_MIN),
  )

  const startTreeResize = (e: React.PointerEvent) => {
    e.preventDefault()
    const startX = e.clientX
    const startW = treeWidth
    const maxTW = Math.round(panelWidth * TREE_WIDTH_MAX_RATIO)
    const onMove = (ev: PointerEvent) => {
      const newW = Math.max(TREE_WIDTH_MIN, Math.min(maxTW, startW + ev.clientX - startX))
      setTreeWidth(newW)
    }
    const onUp = (ev: PointerEvent) => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      const finalW = Math.max(TREE_WIDTH_MIN, Math.min(maxTW, startW + ev.clientX - startX))
      try { localStorage.setItem(TREE_WIDTH_KEY, String(finalW)) } catch { /* ignore */ }
    }
    document.body.style.cursor = 'ew-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
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

  const handleSelectFile = (f: WorkspaceFileInfo) => {
    setSelectedPath(f.path)
    if (isMobile) setMobilePane('preview')
  }

  const handleBackToTree = () => {
    setMobilePane('tree')
  }

  // On mobile, tree pane and preview pane are mutually exclusive full-width views.
  const showTree = !isMobile || mobilePane === 'tree'
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
    <motion.aside
      initial={prefersReducedMotion ? { opacity: 0 } : isMobile ? { opacity: 0 } : { width: 0 }}
      animate={prefersReducedMotion ? { opacity: 1 } : isMobile ? { opacity: 1 } : { width: panelWidth }}
      transition={{ duration: prefersReducedMotion ? 0.01 : 0.22, ease: [0.4, 0, 0.2, 1] }}
      className={cn(
        'fixed bottom-0 right-0 z-40 flex w-full min-h-0 flex-col overflow-hidden border-l border-(--color-border) bg-(--bg-card) shadow-xl md:relative md:inset-y-auto md:right-auto md:z-auto md:w-auto md:shrink-0 md:shadow-none',
        isMobile ? 'mobile-safe-top max-w-none' : isMacOverlay && 'top-(--spacing-app-header)',
      )}
      aria-label="Workspace files"
    >
      {/* Left-edge drag handle to resize the panel */}
      {!isMobile && (
        <div
          className="absolute bottom-0 left-0 top-0 z-10 w-1 cursor-ew-resize transition-colors hover:bg-(--color-accent)/20"
          onPointerDown={resizablePanel.startResize}
          onDoubleClick={resizablePanel.resetWidth}
          title="Drag to resize · double-click to reset"
        />
      )}
      {/* Header */}
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-(--color-border) px-4 py-3">
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
            <h2 className="text-sm font-semibold text-(--color-text)">Workspace</h2>
            <p className="truncate text-xs text-(--color-text-subtle)">
              {isMobile && mobilePane === 'preview' && selected
                ? selected.name
                : <>Files the agent has written into this session{data?.truncated ? ' · list truncated' : ''}</>
              }
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {workspaceRoot && (
            <a
              href={vscodeWorkspaceUrl(workspaceRoot)}
              title="Open in VS Code"
              aria-label="Open in VS Code"
              className="rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            >
              <VscodeIcon size={14} />
            </a>
          )}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={!sessionId || isUploading}
            className="rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-50"
            title="Upload files"
            aria-label="Upload files"
          >
            {isUploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
          </button>
          <button
            onClick={() => folderInputRef.current?.click()}
            disabled={!sessionId || isUploading}
            className="rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-50"
            title="Import folder"
            aria-label="Import folder"
          >
            <FolderUp size={14} />
          </button>
          <button
            onClick={() => refetch()}
            disabled={!sessionId || isFetching}
            className="rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-50"
            title="Refresh"
            aria-label="Refresh"
          >
            <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
          </button>
          <button
            onClick={onClose}
            className="rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            title="Close (Esc)"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>
      </header>

      {/* Workspace path bar + inline picker */}
      {sessionId && (
        <div className="shrink-0 border-b border-(--color-border)">
          <div className="flex items-center gap-2 px-3 py-1.5">
            <FolderOpen size={12} className="shrink-0 text-(--color-text-muted)" />
            <span className="flex-1 truncate font-mono text-xs text-(--color-text-subtle)" title={workspaceRoot ?? undefined}>
              {workspaceRoot ?? 'Session sandbox (default)'}
            </span>
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

      {/* Body: tree + preview split (desktop) / master-detail (mobile) */}
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* Tree — full width on mobile tree pane, resizable on desktop */}
        {showTree && (
          <nav
            className={cn(
              'relative flex flex-col overflow-hidden',
              isMobile ? 'w-full' : 'shrink-0',
            )}
            style={!isMobile ? { width: treeWidth } : undefined}
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
          >
            {isDragging && (
              <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 rounded border-2 border-dashed border-(--color-accent) bg-(--color-accent)/8">
                <Upload size={22} className="text-(--color-accent)" />
                <span className="text-xs font-medium text-(--color-accent)">Drop to upload</span>
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
                <p className="px-2 py-4 text-xs italic text-(--color-text-subtle)">
                  No files yet.  Anything the agent writes will appear here.
                </p>
              ) : visiblePaths && visiblePaths.size === 0 ? (
                <p className="px-2 py-4 text-xs italic text-(--color-text-subtle)">
                  No files match "{searchQuery}"
                </p>
              ) : (
                <TreeNodeView
                  node={tree}
                  depth={0}
                  selectedPath={selectedPath}
                  sessionId={sessionId}
                  workspaceRoot={workspaceRoot}
                  onSelect={handleSelectFile}
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
            className="relative w-px shrink-0 cursor-ew-resize bg-(--color-border) transition-colors hover:bg-(--color-accent)/40"
            onPointerDown={startTreeResize}
            title="Drag to resize"
          />
        )}

        {/* Preview — full width on mobile preview pane, flex-1 on desktop */}
        {showPreview && (
          <div className="min-w-0 flex-1">
            {selected && sessionId ? (
              <PreviewArea key={selected.path} sessionId={sessionId} file={selected} workspaceRoot={workspaceRoot} />
            ) : (
              <EmptyState
                message="Select a file"
                hint="Images, markdown, and code files render inline. Other formats offer download."
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
        {isMobile && 'Tap a file to preview'}
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
    </motion.aside>
  )
}
