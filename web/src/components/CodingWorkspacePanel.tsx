import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ChevronRight, FileText, PanelRightClose, PanelRightOpen, RefreshCw, Search, X } from 'lucide-react'
import { codingWorkspaceFileUrl, getCodingWorkspaceGitDiff, listCodingWorkspaceFiles } from '@/api/client'
import { cn } from '@/lib/utils'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { queryKeys } from '@/queries'
import { formatBytes } from '@/utils/format'
import { workspaceLabel } from '@/utils/workspace'
import { useProjectQuery } from '@/queries/useProjectsQuery'
import { SidePanel } from './shell/SidePanel'
import { CodeGraphPanel } from './CodeGraphPanel'
import { CodingFileViewerPanel } from './CodingFileViewerPanel'
import { FileTypeIcon, FolderTypeIcon } from './FileTypeIcon'
import {
  FileExplorerContextMenu,
  type FileExplorerEntry,
  type FileExplorerMenuActions,
} from './FileExplorerContextMenu'
import { MultiRepoFileTree } from './MultiRepoFileTree'
import { NativeFileTree } from './NativeFileTree'
import { ProjectCodeGraphPanel } from './ProjectCodeGraphPanel'
import type { WorkspaceFileInfo } from '@/api/types'
import { isTauriAvailable, tauriOpenWorkspaceFile } from '@/api/tauri-workspace'
import { openExternalUrl } from '@/lib/open-external'
import { codingExplorerMenuActions } from '@/lib/coding-explorer-actions'
import { useToastStore } from '@/stores/useToastStore'
import { errorMessage } from '@/utils/errors'
import {
  buildTree,
  collectChangedFiles,
  sortTreeNodeChildren,
  type TreeNode,
} from '@/utils/workspaceFileTree'

const CODING_TREE_WIDTH_KEY = STORAGE_KEYS.panels.codingWorkspaceTree
const CODING_TREE_VISIBILITY_KEY = STORAGE_KEYS.workspaceFiles.codingTreeVisible
const CODING_TREE_WIDTH_MIN = 220
const CODING_TREE_WIDTH_DEFAULT = 300
const CODING_TREE_WIDTH_MAX = 420
const CODING_TREE_WIDTH_MAX_RATIO = 0.42
const TREE_DEPTH_INDENT = 12
const TREE_DISCLOSURE_SLOT = 18

function readStoredWidth(key: string, fallback: number): number {
  try {
    const parsed = Number(localStorage.getItem(key))
    return Number.isFinite(parsed)
      ? Math.min(CODING_TREE_WIDTH_MAX, Math.max(CODING_TREE_WIDTH_MIN, parsed))
      : fallback
  } catch {
    return fallback
  }
}

function readStoredBoolean(key: string, fallback: boolean): boolean {
  try {
    const stored = localStorage.getItem(key)
    return stored === null ? fallback : stored === 'true'
  } catch {
    return fallback
  }
}

function pathHasChangedDescendant(path: string, changedPaths: Set<string>): boolean {
  const prefix = `${path}/`
  for (const changedPath of changedPaths) {
    if (changedPath === path || changedPath.startsWith(prefix)) return true
  }
  return false
}

export function TreeNodeView({
  node,
  depth,
  selectedPath,
  selectedSourceWorkspace,
  onFileSelect,
  onFileOpen,
  menuActions,
  changedPaths,
  forceOpen = false,
}: {
  node: TreeNode
  depth: number
  selectedPath?: string | null
  selectedSourceWorkspace?: string | null
  onFileSelect?: (file: WorkspaceFileInfo | null) => void
  onFileOpen?: (file: WorkspaceFileInfo) => void
  menuActions?: FileExplorerMenuActions
  changedPaths: Set<string>
  forceOpen?: boolean
}) {
  const [open, setOpen] = useState(false)
  const isDir = node.children.size > 0 && !node.file
  const children = sortTreeNodeChildren(node)

  if (!isDir && node.file) {
    const file = node.file
    const isSelected = file.path === selectedPath
      && (!selectedSourceWorkspace || file.sourceWorkspace === selectedSourceWorkspace)
    const isChanged = changedPaths.has(file.path)
    const row = (
      <button
        type="button"
        onClick={() => onFileSelect?.(isSelected ? null : file)}
        onDoubleClick={() => onFileOpen?.(file)}
        className={cn(
          'flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-xs transition-colors',
          isSelected
            ? 'bg-(--bg-key) text-(--color-accent)'
            : isChanged
              ? 'text-(--accent-orange-text) hover:bg-(--bg-key)'
              : 'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)',
        )}
        style={{ paddingLeft: 8 + depth * TREE_DEPTH_INDENT + TREE_DISCLOSURE_SLOT }}
        title={file.path}
      >
        <FileTypeIcon name={file.name} mime={file.mime} size={16} />
        <span className="min-w-0 flex-1 truncate font-mono">{node.name}</span>
        {isChanged && (
          <span className="shrink-0 font-mono text-xs font-semibold text-(--accent-orange-text)">
            M
          </span>
        )}
        <span className="shrink-0 text-xs text-(--color-text-subtle)">{formatBytes(file.size)}</span>
      </button>
    )
    if (!menuActions) return row
    const entry: FileExplorerEntry = { path: file.path, name: file.name, isDirectory: false }
    return (
      <FileExplorerContextMenu entry={entry} actions={menuActions}>
        {row}
      </FileExplorerContextMenu>
    )
  }

  const hasChangedDescendant = node.path ? pathHasChangedDescendant(node.path, changedPaths) : false
  const folderRow = node.path
    ? (
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className={cn(
            'flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-xs hover:bg-(--bg-key)',
            hasChangedDescendant ? 'text-(--color-text)' : 'text-(--color-text-2)',
          )}
          style={{ paddingLeft: 8 + depth * TREE_DEPTH_INDENT }}
        >
          <ChevronRight size={12} className={cn('shrink-0 transition-transform', (open || forceOpen) && 'rotate-90')} />
          <FolderTypeIcon open={open || forceOpen} size={16} />
          <span className="min-w-0 flex-1 truncate font-mono">{node.name}</span>
          {hasChangedDescendant && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-(--accent-orange-text)" aria-label="Contains modified files" />}
        </button>
      )
    : null

  return (
    <div>
      {folderRow && (
        menuActions
          ? (
              <FileExplorerContextMenu
                entry={{ path: node.path, name: node.name, isDirectory: true }}
                actions={menuActions}
              >
                {folderRow}
              </FileExplorerContextMenu>
            )
          : folderRow
      )}
      {(open || forceOpen || !node.path) && (
          <div>
            {children.map((child) => (
              <TreeNodeView
                key={child.path}
                node={child}
                depth={node.path ? depth + 1 : 0}
                selectedPath={selectedPath}
                selectedSourceWorkspace={selectedSourceWorkspace}
                onFileSelect={onFileSelect}
                onFileOpen={onFileOpen}
                menuActions={menuActions}
                changedPaths={changedPaths}
                forceOpen={forceOpen}
              />
            ))}
          </div>
      )}
    </div>
  )
}

export function CodingWorkspacePanel({
  workspace,
  open,
  view = 'files',
  onClose,
  mobile = false,
  selectedFilePath = null,
  selectedFile = null,
  onFileSelect,
  initialFileViewMode = 'file',
  onAddFileComment,
  onSendFileToChat,
  projectId = null,
  desktopOverlay = true,
  desktopOverlayInner = false,
  embedded = false,
}: {
  workspace: string
  open: boolean
  view?: 'files' | 'graph'
  onClose: () => void
  mobile?: boolean
  selectedFilePath?: string | null
  selectedFile?: WorkspaceFileInfo | null
  onFileSelect?: (file: WorkspaceFileInfo | null) => void
  initialFileViewMode?: 'file' | 'diff' | 'preview'
  onAddFileComment?: (path: string, startLine: number, endLine: number) => void
  onSendFileToChat?: (action: string, code: string, path: string, startLine: number, endLine: number) => void
  projectId?: string | null
  /** Dock into AppShell's body row instead of covering it. */
  desktopOverlay?: boolean
  desktopOverlayInner?: boolean
  embedded?: boolean
}) {
  const queryClient = useQueryClient()
  const pushToast = useToastStore((state) => state.push)
  const projectQuery = useProjectQuery(projectId)
  const project = projectQuery.data ?? null
  // Drive multi/single-repo mode off the *primed* projectId, not the async
  // project fetch — otherwise the single-workspace diff flashes while the
  // project detail is still loading (see work.tsx projectId priming).
  const isProjectMode = projectId != null
  // Single-workspace queries — dead in project mode (Files/Changed render
  // MultiRepoFileTree/DiffReviewPanel instead), so skip the wasted fetch.
  const files = useQuery({
    queryKey: queryKeys.coding.files(workspace),
    queryFn: () => listCodingWorkspaceFiles(workspace),
    enabled: open && !isProjectMode,
    staleTime: 5_000,
  })
  const diff = useQuery({
    queryKey: queryKeys.coding.diff(workspace),
    queryFn: () => getCodingWorkspaceGitDiff(workspace),
    enabled: open && !isProjectMode,
    staleTime: 5_000,
  })
  const changedFiles = collectChangedFiles(diff.data)
  const changedPaths = new Set(changedFiles.map((file) => file.path))
  const [treeVisible, setTreeVisible] = useState(() =>
    readStoredBoolean(CODING_TREE_VISIBILITY_KEY, true),
  )
  const [treeWidth, setTreeWidth] = useState(() =>
    readStoredWidth(CODING_TREE_WIDTH_KEY, CODING_TREE_WIDTH_DEFAULT),
  )
  const [searchQuery, setSearchQuery] = useState('')
  const [mobilePane, setMobilePane] = useState<'tree' | 'preview'>('tree')
  // Native listings live in NativeFileTree, not the query cache, so Refresh
  // and context-menu mutations need an explicit signal to re-read from disk.
  const [treeReloadKey, setTreeReloadKey] = useState(0)
  const treePaneRef = useRef<HTMLElement>(null)
  const splitBodyRef = useRef<HTMLDivElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const filteredSingleFiles = useMemo(() => {
    const allFiles = files.data?.files ?? []
    const query = searchQuery.trim().toLowerCase()
    return query
      ? allFiles.filter((file) => file.path.toLowerCase().includes(query))
      : allFiles
  }, [files.data?.files, searchQuery])

  const toggleTree = () => {
    setTreeVisible((visible) => {
      const next = !visible
      try { localStorage.setItem(CODING_TREE_VISIBILITY_KEY, String(next)) } catch { /* ignore */ }
      return next
    })
  }

  const startTreeResize = (event: React.PointerEvent) => {
    if (mobile) return
    event.preventDefault()
    event.stopPropagation()
    const startX = event.clientX
    const startWidth = treePaneRef.current?.getBoundingClientRect().width ?? treeWidth
    const panelWidth = splitBodyRef.current?.getBoundingClientRect().width ?? CODING_TREE_WIDTH_DEFAULT * 2
    const maxWidth = Math.max(
      CODING_TREE_WIDTH_MIN,
      Math.min(CODING_TREE_WIDTH_MAX, Math.floor(panelWidth * CODING_TREE_WIDTH_MAX_RATIO)),
    )
    let liveWidth = startWidth

    const handleMove = (pointerEvent: PointerEvent) => {
      liveWidth = Math.max(
        CODING_TREE_WIDTH_MIN,
        Math.min(maxWidth, startWidth + startX - pointerEvent.clientX),
      )
      if (treePaneRef.current) treePaneRef.current.style.width = `${liveWidth}px`
    }
    const handleUp = () => {
      window.removeEventListener('pointermove', handleMove)
      window.removeEventListener('pointerup', handleUp)
      window.removeEventListener('pointercancel', handleUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      setTreeWidth(liveWidth)
      try { localStorage.setItem(CODING_TREE_WIDTH_KEY, String(liveWidth)) } catch { /* ignore */ }
    }

    document.body.style.cursor = 'ew-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', handleMove)
    window.addEventListener('pointerup', handleUp, { once: true })
    window.addEventListener('pointercancel', handleUp, { once: true })
  }

  const resetTreeWidth = () => {
    setTreeWidth(CODING_TREE_WIDTH_DEFAULT)
    try { localStorage.setItem(CODING_TREE_WIDTH_KEY, String(CODING_TREE_WIDTH_DEFAULT)) } catch { /* ignore */ }
  }

  const handleFileSelect = useCallback((file: WorkspaceFileInfo | null) => {
    onFileSelect?.(file)
    if (mobile && file) setMobilePane('preview')
  }, [mobile, onFileSelect])

  const handleClosePreview = () => {
    onFileSelect?.(null)
    if (mobile) setMobilePane('tree')
  }

  const handleOpenFile = async (file: WorkspaceFileInfo) => {
    const sourceWorkspace = file.sourceWorkspace ?? workspace
    try {
      if (isTauriAvailable()) {
        await tauriOpenWorkspaceFile(sourceWorkspace, file.path)
      } else {
        await openExternalUrl(codingWorkspaceFileUrl(sourceWorkspace, file.path))
      }
    } catch (error) {
      pushToast({
        tone: 'error',
        title: `Could not open ${file.name}`,
        description: errorMessage(error),
      })
    }
  }

  const menuActions = useMemo<FileExplorerMenuActions>(() => codingExplorerMenuActions({
    workspace,
    queryClient,
    onPreview: (entry) => {
      const file = files.data?.files.find((item) => item.path === entry.path)
      if (file) handleFileSelect(file)
    },
    onChanged: () => setTreeReloadKey((key) => key + 1),
  }), [files.data?.files, handleFileSelect, queryClient, workspace])

  // The native tree sees files the gitignore-filtered HTTP listing does not,
  // so preview builds the file info from the row itself instead of looking it
  // up in that listing.
  const nativeMenuActions = useMemo<FileExplorerMenuActions>(() => ({
    ...menuActions,
    onPreview: (entry) => handleFileSelect({
      path: entry.path,
      name: entry.name,
      size: entry.size ?? 0,
      mtime: entry.mtime ?? 0,
      mime: entry.mime ?? '',
    }),
  }), [handleFileSelect, menuActions])

  const refreshFiles = async () => {
    setTreeReloadKey((key) => key + 1)
    if (isProjectMode && project) {
      await Promise.all(project.workspaces.flatMap((item) => [
        queryClient.invalidateQueries({ queryKey: queryKeys.coding.files(item.path) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.coding.diff(item.path) }),
      ]))
      return
    }
    await Promise.all([files.refetch(), diff.refetch()])
  }

  const showTree = mobile ? mobilePane === 'tree' : treeVisible
  const showPreview = mobile ? mobilePane === 'preview' : true

  useEffect(() => {
    if (!open || !showTree) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') {
        event.preventDefault()
        searchInputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, showTree])

  if (!open) return null

  return (
    <SidePanel
      storageKey={STORAGE_KEYS.panels.codingWorkspace}
      defaultWidth={440}
      minWidth={360}
      maxWidth={Math.min(720, Math.max(360, Math.floor((typeof window === 'undefined' ? 720 : window.innerWidth) - 320)))}
      mobileOverlay
      desktopOverlay={desktopOverlay}
      desktopOverlayInner={desktopOverlayInner}
      fillParent={embedded}
      mobile={mobile}
      resizeLabel="Resize workspace panel"
      className="bg-(--bg-page)"
    >
        {!embedded && (
          <header className="flex shrink-0 items-center justify-between gap-3 border-b border-(--color-border) px-3 py-2">
          <div className="flex min-w-0 items-center gap-2">
            {view === 'files' && mobile && mobilePane === 'preview' && (
              <button
                type="button"
                onClick={() => setMobilePane('tree')}
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
                aria-label="Back to coding file tree"
              >
                <ArrowLeft size={14} />
              </button>
            )}
            <div className="min-w-0">
              <h2 className="truncate text-sm font-semibold text-(--color-text)">
                {mobile && mobilePane === 'preview' && selectedFile
                  ? selectedFile.name
                  : isProjectMode ? 'Project' : 'Workspace'}
              </h2>
              {isProjectMode ? (
              project ? (
                <p className="truncate text-xs text-(--color-text-subtle)">
                  {project.name}
                  <span className="text-(--color-text-muted)"> · {project.workspaces.length} repos</span>
                </p>
              ) : (
                <p className="truncate text-xs text-(--color-text-subtle)">Loading project…</p>
              )
            ) : (
              <p className="truncate font-mono text-xs text-(--color-text-subtle)" title={workspace}>
                {workspaceLabel(workspace)}
              </p>
              )}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {view === 'files' && (
              <button
                type="button"
                onClick={() => void refreshFiles()}
                className="rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                aria-label="Refresh coding files"
                title="Refresh files"
              >
                <RefreshCw size={14} />
              </button>
            )}
            {view === 'files' && !mobile && (
              <button
                type="button"
                onClick={toggleTree}
                className={cn(
                  'rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)',
                  treeVisible && 'bg-(--bg-key) text-(--color-text)',
                )}
                aria-label={treeVisible ? 'Hide coding file tree' : 'Show coding file tree'}
                title={treeVisible ? 'Hide file tree' : 'Show file tree'}
                aria-pressed={treeVisible}
              >
                {treeVisible ? <PanelRightClose size={15} /> : <PanelRightOpen size={15} />}
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
              aria-label="Close workspace panel"
              title="Close"
            >
              <X size={16} />
            </button>
          </div>
          </header>
        )}
        {view === 'graph' ? (
          <div className="flex min-h-0 flex-1 flex-col">
            {isProjectMode ? (
              project ? (
                <ProjectCodeGraphPanel project={project} onFileSelect={onFileSelect} />
              ) : (
                <p className="px-2 py-4 text-xs text-(--color-text-subtle)">Loading project repositories…</p>
              )
            ) : (
              <div className="min-h-0 flex-1">
                <CodeGraphPanel workspace={workspace} onFileSelect={onFileSelect} />
              </div>
            )}
          </div>
        ) : (
          <div ref={splitBodyRef} className="flex min-h-0 flex-1 overflow-hidden">
            {showPreview && (
              <div className="order-1 min-w-0 flex-1">
                {selectedFile ? (
                  <CodingFileViewerPanel
                    key={`${selectedFile.path}:${initialFileViewMode}`}
                    workspace={selectedFile.sourceWorkspace ?? workspace}
                    file={selectedFile}
                    embedded
                    desktopOverlay={false}
                    initialViewMode={initialFileViewMode}
                    onAddComment={onAddFileComment}
                    onSendToChat={onSendFileToChat}
                    onClose={handleClosePreview}
                    fileTreeVisible={showTree}
                    onToggleFileTree={embedded && !mobile && !showTree ? toggleTree : undefined}
                  />
                ) : (
                  <div className="relative flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
                    {embedded && !mobile && !showTree && (
                      <button
                        type="button"
                        onClick={toggleTree}
                        className="absolute right-2 top-2 flex h-7 w-7 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                        aria-label="Show coding file tree"
                        title="Show file tree"
                      >
                        <PanelRightOpen size={14} />
                      </button>
                    )}
                    <FileText size={26} className="text-(--color-text-subtle)" />
                    <p className="text-sm text-(--color-text-2)">Select a file</p>
                    <p className="max-w-xs text-xs text-(--color-text-subtle)">
                      Select a file from the project tree to preview it.
                    </p>
                  </div>
                )}
              </div>
            )}

            {!mobile && showTree && showPreview && (
              <div
                role="separator"
                aria-orientation="vertical"
                aria-label="Resize coding file tree"
                aria-valuemin={CODING_TREE_WIDTH_MIN}
                aria-valuemax={CODING_TREE_WIDTH_MAX}
                aria-valuenow={Math.round(treeWidth)}
                title="Drag to resize · double-click to reset"
                onPointerDown={startTreeResize}
                onDoubleClick={resetTreeWidth}
                className="group relative order-2 w-2 shrink-0 cursor-ew-resize"
              >
                <span className="pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-(--color-border) transition-colors group-hover:bg-(--color-accent)/60" />
              </div>
            )}

            {showTree && (
              <nav
                ref={treePaneRef}
                aria-label="Coding project files"
                className={cn(
                  'order-3 flex min-h-0 flex-col overflow-hidden bg-(--bg-page)',
                  mobile ? 'w-full' : 'shrink-0',
                )}
                style={!mobile
                  ? {
                      width: `min(${treeWidth}px, ${CODING_TREE_WIDTH_MAX_RATIO * 100}%)`,
                      minWidth: CODING_TREE_WIDTH_MIN,
                    }
                  : undefined}
              >
                <div className="flex shrink-0 items-center gap-1 border-b border-(--color-border) px-2 py-1.5">
                  <div className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md border border-(--color-border) bg-(--bg-card) px-2 py-1">
                    <Search size={12} className="shrink-0 text-(--color-text-subtle)" />
                    <input
                      ref={searchInputRef}
                      type="text"
                      value={searchQuery}
                      onChange={(event) => setSearchQuery(event.target.value)}
                      placeholder="Search files…"
                      className="w-full bg-transparent text-xs text-(--color-text) outline-none placeholder:text-(--color-text-subtle)"
                    />
                    {searchQuery && (
                      <button
                        type="button"
                        onClick={() => setSearchQuery('')}
                        className="shrink-0 rounded p-0.5 text-(--color-text-subtle) hover:text-(--color-text)"
                        aria-label="Clear coding file search"
                      >
                        <X size={10} />
                      </button>
                    )}
                  </div>
                  {embedded && (
                    <button
                      type="button"
                      onClick={() => void refreshFiles()}
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                      aria-label="Refresh coding files"
                      title="Refresh files"
                    >
                      <RefreshCw size={13} />
                    </button>
                  )}
                  {embedded && !mobile && (
                    <button
                      type="button"
                      onClick={toggleTree}
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-(--bg-key) text-(--color-text) transition-colors hover:bg-(--bg-key-hover)"
                      aria-label="Hide coding file tree"
                      title="Hide file tree"
                      aria-pressed={true}
                    >
                      <PanelRightClose size={14} />
                    </button>
                  )}
                </div>
                <div className="min-h-0 flex-1 overflow-auto p-2">
                  {isProjectMode ? (
                    project ? (
                      <MultiRepoFileTree
                        project={project}
                        selectedFilePath={selectedFilePath}
                        selectedSourceWorkspace={selectedFile?.sourceWorkspace}
                        searchQuery={searchQuery}
                        onFileSelect={handleFileSelect}
                        onFileOpen={(file) => void handleOpenFile(file)}
                      />
                    ) : (
                      <p className="px-2 py-4 text-xs text-(--color-text-subtle)">Loading project repositories…</p>
                    )
                  ) : (
                    // The native tree reads the filesystem directly, so it
                    // must not be gated on the HTTP listing it replaces —
                    // that made a failed or gitignore-emptied listing hide a
                    // perfectly readable workspace.
                    isTauriAvailable() && !searchQuery.trim() ? (
                      <NativeFileTree
                        workspaceRoot={workspace}
                        selectedPath={selectedFilePath}
                        menuActions={nativeMenuActions}
                        reloadKey={treeReloadKey}
                        onFileSelect={(entry) => {
                          if (!entry) {
                            handleFileSelect(null)
                            return
                          }
                          handleFileSelect({
                            path: entry.path,
                            name: entry.name,
                            size: entry.size,
                            mtime: entry.mtime,
                            mime: entry.mime,
                          })
                        }}
                        onFileOpen={(entry) => void handleOpenFile({
                          path: entry.path,
                          name: entry.name,
                          size: entry.size,
                          mtime: entry.mtime,
                          mime: entry.mime,
                        })}
                        className="flex-1 overflow-auto"
                      />
                    ) : files.isLoading ? (
                      <p className="px-2 py-4 text-xs text-(--color-text-subtle)">Loading files…</p>
                    ) : files.isError ? (
                      <p className="px-2 py-4 text-xs text-(--color-error)">Failed to load files</p>
                    ) : (
                      <div className="p-2">
                        {filteredSingleFiles.length === 0
                          ? (
                              <p className="px-2 py-4 text-xs text-(--color-text-subtle)">
                                {searchQuery ? `No files match "${searchQuery}"` : 'No files shown'}
                              </p>
                            )
                          : Array.from(buildTree(filteredSingleFiles).children.values()).map((node) => (
                              <TreeNodeView
                                key={node.path}
                                node={node}
                                depth={0}
                                menuActions={menuActions}
                                selectedPath={selectedFilePath}
                                selectedSourceWorkspace={selectedFile?.sourceWorkspace}
                                onFileSelect={handleFileSelect}
                                onFileOpen={(file) => void handleOpenFile(file)}
                                changedPaths={changedPaths}
                                forceOpen={Boolean(searchQuery.trim())}
                              />
                            ))
                        }
                      </div>
                    )
                  )}
                </div>
              </nav>
            )}
          </div>
        )}
    </SidePanel>
  )
}
