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
 * Text/code files render as-is in a plain monospace view. PDF, DOCX, PPTX and
 * XLSX share the host-owned document reader backed by inert preview HTML.
 * Everything else can be opened in the system's default desktop app.
 *
 * Data flow:
 *   - GET /api/team/{sid}/files      → listing (polled on open, invalidated
 *                                       by team store after write/edit/rm)
 *   - GET /api/team/{sid}/media/{p}  → file bytes (fetched by preview only
 *                                       when the user selects a text file;
 *                                       images use the URL directly as src)
 */

import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Editor from '@monaco-editor/react'
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
  FolderUp,
  MoreHorizontal,
  LocateFixed,
  PanelRightClose,
  PanelRightOpen,
  Eye,
  Code2,
} from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { cn } from '@/lib/utils'
import {
  workspaceMediaUrl,
  updateSessionWorkspace,
  uploadWorkspaceFiles,
  createWorkspaceEntry,
  copyWorkspaceFile,
  moveWorkspaceFile,
  deleteWorkspaceFile,
  browseWorkspaces,
} from '@/api/client'
import {
  decodeBase64Utf8,
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
import { languageForExt, useMonacoTheme, useSafeMonaco } from '@/hooks/useMonacoTheme'
import { formatBytes } from '@/utils/format'
import { errorMessage } from '@/utils/errors'
import { MarkdownBlock } from '@/utils/markdown'
import { SidePanel } from './shell/SidePanel'
import { useUIStore } from '@/stores/useUIStore'
import { getWorkspacePanelLayout } from '@/lib/workspace-panel-layout'
import { ImageLightbox } from './ImageLightbox'
import {
  FileExplorerContextMenu,
  type FileExplorerEntry,
  type FileExplorerMenuActions,
} from './FileExplorerContextMenu'
import { FileTypeIcon, FolderTypeIcon } from './FileTypeIcon'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from './ui/dropdown-menu'
import { openExternalUrl } from '@/lib/open-external'
import { downloadWorkspaceFile } from '@/lib/workspace-download'
import {
  isWorkspaceCodeExtension,
  isWorkspaceDocumentKind,
  workspaceFileExtension,
  workspaceFileKind,
} from '@/lib/workspace-file-kind'
import type { WorkspaceFileInfo, WorkspaceFilesResponse } from '@/api/types'
import { buildTree, sortTreeNodeChildren, type TreeNode } from '@/utils/workspaceFileTree'
import { WorkspaceHtmlPreview } from './workspace-html-preview'

const DocumentPreview = lazy(() =>
  import('./workspace-document-preview').then((module) => ({ default: module.WorkspaceDocumentPreview })),
)

// ── File-type helpers ─────────────────────────────────────────────────────────

/**
 * Read a workspace file as text, natively on desktop and over HTTP on web.
 *
 * Shared by the text preview, the "copy contents" button and the explorer's
 * context menu so all three agree on where a file's bytes come from.
 */
async function readWorkspaceFileText(
  sessionId: string,
  workspaceRoot: string | null | undefined,
  path: string,
): Promise<string> {
  if (isTauriAvailable() && workspaceRoot) {
    return decodeBase64Utf8(await tauriReadWorkspaceFile(workspaceRoot, path))
  }
  const response = await fetch(workspaceMediaUrl(sessionId, path))
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.text()
}

// ── Resize constants ─────────────────────────────────────────────────────────

const PANEL_WIDTH_KEY = STORAGE_KEYS.panels.workspace
const TREE_WIDTH_KEY = STORAGE_KEYS.panels.workspaceTree
const TREE_VISIBILITY_KEY = STORAGE_KEYS.workspaceFiles.treeVisible
const TREE_WIDTH_MIN = 220
const TREE_WIDTH_DEFAULT = 280
const TREE_WIDTH_MAX = 380
const TREE_WIDTH_MAX_RATIO = 0.42
const PREVIEW_MIN_WIDTH = 520
const TREE_DIVIDER_WIDTH = 8
const SPLIT_MIN_WIDTH = PREVIEW_MIN_WIDTH + TREE_WIDTH_DEFAULT + TREE_DIVIDER_WIDTH
const TREE_DEPTH_INDENT = 12
const TREE_DISCLOSURE_SLOT = 18

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
  onSelect,
  menuActions,
  visiblePaths,
  defaultOpen,
}: {
  node: TreeNode
  depth: number
  selectedPath: string | null
  onSelect: (file: WorkspaceFileInfo) => void
  menuActions: FileExplorerMenuActions
  visiblePaths: Set<string> | null
  defaultOpen: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const isDir = node.children.size > 0 && !node.file

  // Keep folders open when a search filter is active so results are visible.
  const effectiveOpen = visiblePaths ? true : open

  // Match the coding workspace tree ordering: folders first, then files,
  // with natural alphabetical sorting.
  const children = sortTreeNodeChildren(node)

  // When a filter is active, prune children that are not in visiblePaths.
  const filteredChildren = visiblePaths
    ? children.filter((child) => visiblePaths.has(child.path))
    : children

  // If filtering and nothing matches under this node, hide the whole subtree.
  if (visiblePaths && !visiblePaths.has(node.path) && filteredChildren.length === 0) {
    return null
  }

  if (!isDir && node.file) {
    // ── File leaf ──────────────────────────────────────────────────────────
    const file = node.file
    const isSelected = file.path === selectedPath
    const entry: FileExplorerEntry = { path: file.path, name: file.name, isDirectory: false }

    return (
      <FileExplorerContextMenu entry={entry} actions={menuActions}>
        <button
          type="button"
          onClick={() => onSelect(file)}
          onDoubleClick={() => void menuActions.onOpenExternally?.(entry)}
          className={cn(
            'flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-xs transition-colors',
            isSelected
              ? 'bg-(--bg-key) text-(--color-accent)'
              : 'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)',
          )}
          style={{ paddingLeft: 8 + depth * TREE_DEPTH_INDENT + TREE_DISCLOSURE_SLOT }}
          title={file.path}
        >
          <FileTypeIcon name={file.name} mime={file.mime} size={16} />
          <span className="min-w-0 flex-1 truncate font-mono">{node.name}</span>
          <span className="shrink-0 text-xs text-(--color-text-subtle)">
            {formatBytes(file.size)}
          </span>
        </button>
      </FileExplorerContextMenu>
    )
  }

  // ── Folder node ─────────────────────────────────────────────────────────
  const childRows = filteredChildren.map((child) => (
    <TreeNodeView
      key={child.path}
      node={child}
      depth={node.path ? depth + 1 : 0}
      selectedPath={selectedPath}
      onSelect={onSelect}
      menuActions={menuActions}
      visiblePaths={visiblePaths}
      defaultOpen={node.path ? false : defaultOpen}
    />
  ))

  if (!node.path) {
    // Root — render children directly without a folder row.
    return <>{childRows}</>
  }

  const folderEntry: FileExplorerEntry = { path: node.path, name: node.name, isDirectory: true }

  return (
    <div>
      <FileExplorerContextMenu entry={folderEntry} actions={menuActions}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className={cn(
            'flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-xs hover:bg-(--bg-key)',
            effectiveOpen ? 'text-(--color-text)' : 'text-(--color-text-2)',
          )}
          style={{ paddingLeft: 8 + depth * TREE_DEPTH_INDENT }}
        >
          <ChevronRight
            size={12}
            className={cn('shrink-0 transition-transform', effectiveOpen && 'rotate-90')}
          />
          <FolderTypeIcon open={effectiveOpen} size={16} />
          <span className="min-w-0 flex-1 truncate font-mono">{node.name}</span>
        </button>
      </FileExplorerContextMenu>
      {effectiveOpen && childRows}
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
  const monaco = useSafeMonaco()
  const theme = useMonacoTheme(monaco)
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
        const text = await readWorkspaceFileText(sessionId, workspaceRoot, file.path)
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

  const ext = workspaceFileExtension(file.name)
  const isMarkdown = ext === 'md' || ext === 'markdown'
  const isCode = !isMarkdown && isWorkspaceCodeExtension(ext)

  if (isMarkdown) {
    return (
      <div className="h-full overflow-auto px-6 py-4">
        <MarkdownBlock content={content} sessionId={sessionId} />
      </div>
    )
  }

  if (isCode) {
    return (
      <div className="h-full min-h-0 w-full overflow-hidden bg-(--bg-page)">
        <Editor
          height="100%"
          theme={theme}
          language={languageForExt(ext)}
          value={content}
          loading={(
            <pre className="h-full overflow-auto p-3 font-mono text-xs leading-5 text-(--color-text)">
              {content}
            </pre>
          )}
          options={{
            readOnly: true,
            domReadOnly: true,
            ariaLabel: `${file.name} source preview`,
            automaticLayout: true,
            contextmenu: true,
            folding: true,
            fontSize: 13,
            glyphMargin: false,
            lineHeight: 20,
            lineNumbers: 'on',
            minimap: { enabled: false },
            overviewRulerBorder: false,
            renderLineHighlight: 'none',
            scrollBeyondLastLine: false,
            scrollbar: {
              horizontalScrollbarSize: 10,
              verticalScrollbarSize: 10,
            },
            wordWrap: 'off',
          }}
        />
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

function RichPreviewLoading({ label }: { label: string }) {
  return (
    <div className="flex h-full items-center justify-center gap-2 text-(--color-text-subtle)">
      <Loader2 size={17} className="animate-spin" aria-hidden="true" />
      <span className="text-xs">Loading {label} engine…</span>
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
      const text = await readWorkspaceFileText(sessionId, workspaceRoot, file.path)
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
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2) disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-(--color-text-muted)"
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
  fileTreeVisible = false,
  onToggleFileTree,
  onBackToTree,
}: {
  sessionId: string
  file: WorkspaceFileInfo
  workspaceRoot: string | null
  onOpen: (file: WorkspaceFileInfo) => void
  onReveal: (file: WorkspaceFileInfo) => void
  isDesktop: boolean
  fileTreeVisible?: boolean
  onToggleFileTree?: () => void
  onBackToTree?: () => void
}) {
  const kind = workspaceFileKind(file)
  const extension = workspaceFileExtension(file.name)
  const isHtml = extension === 'html' || extension === 'htm'
  const [htmlView, setHtmlView] = useState<'preview' | 'source'>('preview')
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-(--color-border) px-2">
        {onBackToTree && (
          <button
            type="button"
            onClick={onBackToTree}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Back to file list"
            title="Back to file list"
          >
            <ArrowLeft size={14} />
          </button>
        )}
        <div
          className="flex min-w-0 flex-1 items-baseline gap-1.5"
          title={`${file.path} · ${formatBytes(file.size)} · ${file.mime}`}
        >
          <div className="truncate text-xs font-semibold text-(--color-text)">{file.path}</div>
          <span className="shrink-0 text-[10px] text-(--color-text-subtle)">{formatBytes(file.size)}</span>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          {isHtml && (
            <div className="mr-0.5 flex rounded-md border border-(--color-border) p-0.5" role="group" aria-label="HTML view">
              <button
                type="button"
                onClick={() => setHtmlView('preview')}
                title="Preview"
                aria-label="Preview HTML"
                className={cn(
                  'flex h-6 w-6 items-center justify-center rounded-xs transition-colors',
                  htmlView === 'preview'
                    ? 'bg-(--bg-key) text-(--color-text)'
                    : 'text-(--color-text-muted) hover:text-(--color-text-2)',
                )}
                aria-pressed={htmlView === 'preview'}
              >
                <Eye size={12} />
              </button>
              <button
                type="button"
                onClick={() => setHtmlView('source')}
                title="Source"
                aria-label="View HTML source"
                className={cn(
                  'flex h-6 w-6 items-center justify-center rounded-xs transition-colors',
                  htmlView === 'source'
                    ? 'bg-(--bg-key) text-(--color-text)'
                    : 'text-(--color-text-muted) hover:text-(--color-text-2)',
                )}
                aria-pressed={htmlView === 'source'}
              >
                <Code2 size={12} />
              </button>
            </div>
          )}
          <button
            type="button"
            onClick={() => onOpen(file)}
            className="flex h-7 w-7 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            title="Open in default app"
            aria-label="Open in default app"
          >
            <ExternalLink size={13} />
          </button>
          {isDesktop && workspaceRoot && (
            <button
              type="button"
              onClick={() => onReveal(file)}
              className="flex h-7 w-7 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
              title="Show file in folder"
              aria-label="Show file in folder"
            >
              <LocateFixed size={13} />
            </button>
          )}
          {kind === 'text' && <CopyContentsButton sessionId={sessionId} file={file} workspaceRoot={workspaceRoot} />}
          {onToggleFileTree && (
            <button
              type="button"
              onClick={onToggleFileTree}
              className={cn(
                'flex h-7 w-7 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)',
                fileTreeVisible && 'bg-(--bg-key) text-(--color-text)',
              )}
              title={fileTreeVisible ? 'Hide file tree' : 'Show file tree'}
              aria-label={fileTreeVisible ? 'Hide file tree' : 'Show file tree'}
              aria-pressed={fileTreeVisible}
            >
              {fileTreeVisible ? <PanelRightClose size={14} /> : <PanelRightOpen size={14} />}
            </button>
          )}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">
        {isHtml && htmlView === 'preview' ? (
          <WorkspaceHtmlPreview
            key={`${file.path}:${file.mtime}`}
            sessionId={sessionId}
            file={file}
          />
        ) : kind === 'image' ? (
          <ImagePreview sessionId={sessionId} file={file} />
        ) : kind === 'text' ? (
          <TextPreview
            key={`${file.path}:${file.mtime}`}
            sessionId={sessionId}
            file={file}
            workspaceRoot={workspaceRoot}
          />
        ) : isWorkspaceDocumentKind(kind) ? (
          <Suspense fallback={<RichPreviewLoading label="document" />}>
            <DocumentPreview key={`${file.path}:${file.mtime}`} sessionId={sessionId} file={file} />
          </Suspense>
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
  const workspaceFileRequest = useUIStore((state) => state.workspaceFileRequest)
  const clearWorkspaceFileRequest = useUIStore((state) => state.clearWorkspaceFileRequest)
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
  const [splitBodyWidth, setSplitBodyWidth] = useState<number | null>(null)

  useEffect(() => {
    const body = splitBodyRef.current
    if (!body || typeof ResizeObserver === 'undefined') return
    const updateWidth = (width: number) => setSplitBodyWidth(Math.round(width))
    updateWidth(body.getBoundingClientRect().width)
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (entry) updateWidth(entry.contentRect.width)
    })
    observer.observe(body)
    return () => observer.disconnect()
  }, [open])

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
  const visibleFileCount = useMemo(
    () => visiblePaths
      ? files.reduce((count, file) => count + (visiblePaths.has(file.path) ? 1 : 0), 0)
      : files.length,
    [files, visiblePaths],
  )
  const refreshedRequestRef = useRef<number | null>(null)

  // Artifact links in the transcript open Files and request one path. Refresh
  // once for that request (the file may have landed after the cached listing),
  // then select it as soon as it appears in the workspace response.
  useEffect(() => {
    if (
      !open
      || !sessionId
      || workspaceFileRequest?.sessionId !== sessionId
      || refreshedRequestRef.current === workspaceFileRequest.id
    ) return
    refreshedRequestRef.current = workspaceFileRequest.id
    void refetch()
  }, [open, refetch, sessionId, workspaceFileRequest])

  useEffect(() => {
    if (!open || !sessionId || workspaceFileRequest?.sessionId !== sessionId) return
    const requested = files.find((file) => file.path === workspaceFileRequest.path)
      ?? (!workspaceFileRequest.path.includes('/')
        ? files.find((file) => file.name === workspaceFileRequest.path)
        : undefined)
    if (!requested) return
    setSelectedPath(requested.path)
    setMobilePane('preview')
    clearWorkspaceFileRequest(workspaceFileRequest.id)
  }, [clearWorkspaceFileRequest, files, open, sessionId, workspaceFileRequest])

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
            queryClient.setQueryData(queryKeys.team.workspaceRoot(sessionId), {
              session_id: sessionId,
              workspace_root: result.workspace_root,
            })
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
      setPickerPath(result.path)
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
      queryClient.setQueryData(queryKeys.team.workspaceRoot(sessionId), {
        session_id: sessionId,
        workspace_root: result.workspace_root,
      })
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

  // ── Explorer context-menu actions ───────────────────────────────────────────
  //
  // Built once for the whole tree: every row's menu takes the clicked entry as
  // an argument, so the callbacks stay path-based and the memo never has to
  // change as the selection moves. Failures surface as toasts from the menu.

  const menuActions = useMemo<FileExplorerMenuActions>(() => {
    if (!sessionId) return {}
    const applyListing = (result: WorkspaceFilesResponse) => {
      queryClient.setQueryData(queryKeys.team.files(sessionId), result)
    }
    const childPath = (parentDir: string, name: string) => (
      parentDir ? `${parentDir}/${name}` : name
    )
    const siblingPath = (path: string, name: string) => {
      const index = path.lastIndexOf('/')
      return index < 0 ? name : `${path.slice(0, index + 1)}${name}`
    }
    return {
      root: workspaceRoot,
      onPreview: (entry) => {
        setSelectedPath(entry.path)
        setMobilePane('preview')
      },
      onOpenExternally: async (entry) => {
        if (isTauri && workspaceRoot) {
          await tauriOpenWorkspaceFile(workspaceRoot, entry.path)
          return
        }
        await openExternalUrl(workspaceMediaUrl(sessionId, entry.path))
      },
      onReveal: isTauri && workspaceRoot
        ? (entry) => tauriRevealWorkspacePath(workspaceRoot, entry.path)
        : undefined,
      readText: (entry) => readWorkspaceFileText(sessionId, workspaceRoot, entry.path),
      onDownload: (entry) => downloadWorkspaceFile(sessionId, entry),
      onCreate: async (parentDir, name, kind) => {
        applyListing(await createWorkspaceEntry(sessionId, childPath(parentDir, name), kind))
      },
      onRename: async (entry, name) => {
        applyListing(await moveWorkspaceFile(sessionId, entry.path, siblingPath(entry.path, name)))
      },
      onDuplicate: async (entry, name) => {
        applyListing(await copyWorkspaceFile(sessionId, entry.path, siblingPath(entry.path, name)))
      },
      onDelete: async (entry) => {
        applyListing(await deleteWorkspaceFile(sessionId, entry.path, {
          recursive: entry.isDirectory,
        }))
      },
    }
  }, [isTauri, queryClient, sessionId, workspaceRoot])

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
      setUploadError(errorMessage(err) || 'Failed to show file in folder')
    }
  }, [isTauri, workspaceRoot])

  const handleRevealWorkspace = useCallback(async () => {
    if (!isTauri || !workspaceRoot) return
    setUploadError(null)
    try {
      await tauriRevealWorkspacePath(workspaceRoot)
    } catch (err) {
      setUploadError(errorMessage(err) || 'Failed to show workspace in folder')
    }
  }, [isTauri, workspaceRoot])

  const handleSelectFile = (f: WorkspaceFileInfo) => {
    setSelectedPath(f.path)
    setMobilePane('preview')
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

  // Narrow panels use a master-detail layout even at the exact desktop/mobile
  // breakpoint. This is container-driven because an embedded workbench can be
  // much narrower than the viewport that contains it.
  const isSinglePane = isMobile || splitBodyWidth === null || splitBodyWidth < SPLIT_MIN_WIDTH
  const showTree = isSinglePane ? mobilePane === 'tree' : desktopTreeVisible
  const showPreview = !isSinglePane || mobilePane === 'preview'
  const maxTreeWidth = splitBodyWidth === null
    ? TREE_WIDTH_DEFAULT
    : Math.max(
        TREE_WIDTH_MIN,
        Math.min(
          TREE_WIDTH_MAX,
          Math.round(splitBodyWidth * TREE_WIDTH_MAX_RATIO),
          splitBodyWidth - PREVIEW_MIN_WIDTH - TREE_DIVIDER_WIDTH,
        ),
      )
  const renderedTreeWidth = Math.min(treeWidth, maxTreeWidth)

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
      className="bg-(--bg-page)"
    >
      {/* Standalone/mobile panel header; embedded workbench already owns this chrome. */}
      {!embedded && (
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-(--color-border) px-3 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {/* Mobile back button — only shown in preview pane */}
          {isSinglePane && mobilePane === 'preview' && (
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
              {isSinglePane && mobilePane === 'preview' && selected
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
          {!isSinglePane && (
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
      )}

      {/* Workspace path bar + inline picker */}
      {sessionId && (!embedded || isPickerOpen || uploadError) && (
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
                    onClick={() => {
                      setPickerPath(dir.path)
                      void handleBrowse(dir.path)
                    }}
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
              'relative order-3 flex flex-col overflow-hidden bg-(--bg-page)',
              isSinglePane ? 'w-full' : 'shrink-0',
            )}
            style={!isSinglePane
              ? {
                  width: renderedTreeWidth,
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
            {sessionId && (files.length > 0 || embedded) && (
              <div className="flex shrink-0 items-center gap-1 border-b border-(--color-border) px-2 py-1.5">
                <div className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md border border-(--color-border) bg-(--bg-card) px-2 py-1">
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
                {embedded && isTauri && workspaceRoot && (
                  <button
                    type="button"
                    onClick={() => void handleOpenWorkspace()}
                    title="Open workspace folder"
                    aria-label="Open workspace folder"
                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                  >
                    <FolderOpen size={13} />
                  </button>
                )}
                {embedded && (
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      disabled={!sessionId}
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-50"
                      title="Workspace actions"
                      aria-label="Workspace actions"
                    >
                      {isUploading ? <Loader2 size={13} className="animate-spin" /> : <MoreHorizontal size={13} />}
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
                )}
                {embedded && (
                  <button
                    type="button"
                    onClick={() => refetch()}
                    disabled={!sessionId || isFetching}
                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-50"
                    title="Refresh"
                    aria-label="Refresh"
                  >
                    <RefreshCw size={13} className={isFetching ? 'animate-spin' : ''} />
                  </button>
                )}
                {embedded && !isSinglePane && (
                  <button
                    type="button"
                    onClick={toggleDesktopTree}
                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-(--bg-key) text-(--color-text) transition-colors hover:bg-(--bg-key-hover)"
                    title="Hide file tree"
                    aria-label="Hide file tree"
                    aria-pressed={true}
                  >
                    <PanelRightClose size={14} />
                  </button>
                )}
              </div>
            )}
            <div className="min-h-0 flex-1 overflow-auto p-2">
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
                  onSelect={handleSelectFile}
                  menuActions={menuActions}
                  visiblePaths={visiblePaths}
                  defaultOpen
                />
              )}
            </div>
          </nav>
        )}

        {/* Tree/preview drag divider — desktop only */}
        {!isSinglePane && showTree && showPreview && (
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize workspace file tree"
            aria-valuemin={TREE_WIDTH_MIN}
            aria-valuemax={TREE_WIDTH_MAX}
            aria-valuenow={Math.round(treeWidth)}
            className="group relative order-2 w-2 shrink-0 cursor-ew-resize"
            onPointerDown={startTreeResize}
            onDoubleClick={resetTreeWidth}
            title="Drag to resize · double-click to reset"
          >
            <span className="pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-(--color-border) transition-colors group-hover:bg-(--color-accent)/60" />
          </div>
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
                fileTreeVisible={showTree}
                onToggleFileTree={embedded && !isSinglePane && !showTree ? toggleDesktopTree : undefined}
                onBackToTree={embedded && isSinglePane ? handleBackToTree : undefined}
              />
            ) : (
              <div className="relative h-full">
                {embedded && !isSinglePane && !showTree && (
                  <button
                    type="button"
                    onClick={toggleDesktopTree}
                    className="absolute right-2 top-2 z-(--z-panel) flex h-7 w-7 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                    title="Show file tree"
                    aria-label="Show file tree"
                  >
                    <PanelRightOpen size={14} />
                  </button>
                )}
                <EmptyState
                  message="Select a file"
                  hint={isTauri
                    ? 'Single-click to preview. Double-click to open with the default app.'
                    : 'Single-click to preview. Double-click opens the debug media URL.'}
                />
              </div>
            )}
          </div>
        )}
      </div>

      {/* Standalone footer; the embedded tree already communicates its state. */}
      {!embedded && (
      <div className="shrink-0 border-t border-(--color-border) px-4 py-2 text-xs text-(--color-text-muted) pb-safe">
        {files.length > 0 && (
          <span>
            {visiblePaths
              ? `${visibleFileCount} of ${files.length} file${files.length === 1 ? '' : 's'}`
              : `${files.length} file${files.length === 1 ? '' : 's'}`
            }
            {' · '}
          </span>
        )}
        {isMobile
          ? 'Tap a file to preview'
          : isSinglePane
            ? 'Select a file to preview'
            : 'Double-click a file to open it'}
      </div>
      )}

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
