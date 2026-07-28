import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { ChevronRight, FileText, Folder, GitBranch, Network, RefreshCw, Timer, X } from 'lucide-react'
import { useMotionPreset } from '@/lib/motion'
import { getCodingWorkspaceGitDiff, listCodingWorkspaceFiles } from '@/api/client'
import { cn } from '@/lib/utils'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { queryKeys } from '@/queries'
import { formatBytes } from '@/utils/format'
import { workspaceLabel } from '@/utils/workspace'
import { useProjectQuery } from '@/queries/useProjectsQuery'
import { SidePanel } from './shell/SidePanel'
import { CodeGraphPanel } from './CodeGraphPanel'
import { CrossRepoLinksPanel } from './CrossRepoLinksPanel'
import { SourceControlModal } from './SourceControlModal'
import { DiffReviewPanel } from './DiffReviewPanel'
import { MultiRepoFileTree } from './MultiRepoFileTree'
import { NativeFileTree } from './NativeFileTree'
import { ProjectCodeGraphPanel } from './ProjectCodeGraphPanel'
import { TaskTimelinePanel } from './TaskTimelinePanel'
import type { WorkspaceFileInfo } from '@/api/types'
import { isTauriAvailable } from '@/api/tauri-workspace'
import {
  buildTree,
  collectChangedFiles,
  type ChangedFileStatus,
  type TreeNode,
} from '@/utils/workspaceFileTree'

const CHANGED_STATUS_LABELS: Record<ChangedFileStatus, string> = {
  A: 'Added',
  M: 'Modified',
  D: 'Deleted',
}

const WORKSPACE_TABS = [
  { key: 'changed' as const, label: 'Source control', Icon: GitBranch },
  { key: 'files' as const, label: 'Files', Icon: Folder },
  { key: 'graph' as const, label: 'Graph', Icon: Network },
  { key: 'progress' as const, label: 'Progress', Icon: Timer },
]

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
  onFileSelect,
  changedPaths,
}: {
  node: TreeNode
  depth: number
  selectedPath?: string | null
  onFileSelect?: (file: WorkspaceFileInfo | null) => void
  changedPaths: Set<string>
}) {
  const preset = useMotionPreset()
  const [open, setOpen] = useState(false)
  const isDir = node.children.size > 0 && !node.file
  const children = Array.from(node.children.values()).sort((a, b) => {
    const aDir = a.children.size > 0 && !a.file
    const bDir = b.children.size > 0 && !b.file
    if (aDir !== bDir) return aDir ? -1 : 1
    return a.name.localeCompare(b.name)
  })

  if (!isDir && node.file) {
    const isSelected = node.file.path === selectedPath
    const isChanged = changedPaths.has(node.file.path)
    return (
      <button
        type="button"
        onClick={() => onFileSelect?.(isSelected ? null : node.file!)}
        className={cn(
          'flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-xs transition-colors',
          isSelected
            ? 'bg-(--bg-key) text-(--color-accent)'
            : isChanged
              ? 'text-(--accent-orange-text) hover:bg-(--bg-key)'
              : 'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)',
        )}
        style={{ paddingLeft: 8 + depth * 12 }}
        title={node.file.path}
      >
        <FileText size={12} className={cn('shrink-0', isChanged ? 'text-(--accent-orange-text)' : 'text-(--color-text-subtle)')} />
        <span className="min-w-0 flex-1 truncate font-mono">{node.name}</span>
        {isChanged && (
          <span className="shrink-0 font-mono text-xs font-semibold text-(--accent-orange-text)">
            M
          </span>
        )}
        <span className="shrink-0 text-xs text-(--color-text-subtle)">{formatBytes(node.file.size)}</span>
      </button>
    )
  }

  const hasChangedDescendant = node.path ? pathHasChangedDescendant(node.path, changedPaths) : false

  return (
    <div>
      {node.path && (
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className={cn(
            'flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-xs hover:bg-(--bg-key)',
            hasChangedDescendant ? 'text-(--color-text)' : 'text-(--color-text-2)',
          )}
          style={{ paddingLeft: 8 + depth * 12 }}
        >
          <ChevronRight size={12} className={cn('shrink-0 transition-transform', open && 'rotate-90')} />
          <Folder size={12} className={cn('shrink-0', hasChangedDescendant ? 'text-(--accent-orange-text)' : 'text-(--color-accent)')} />
          <span className="min-w-0 flex-1 truncate font-mono">{node.name}</span>
          {hasChangedDescendant && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-(--accent-orange-text)" aria-label="Contains modified files" />}
        </button>
      )}
      <AnimatePresence initial={false}>
        {(open || !node.path) && (
          <motion.div
            key="tree-children"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={preset.transition}
            className="overflow-hidden"
          >
            {children.map((child) => (
              <TreeNodeView key={child.path} node={child} depth={node.path ? depth + 1 : 0} selectedPath={selectedPath} onFileSelect={onFileSelect} changedPaths={changedPaths} />
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export function CodingWorkspacePanel({
  workspace,
  open,
  initialTab = 'changed',
  onClose,
  mobile = false,
  selectedFilePath = null,
  onFileSelect,
  sessionId = null,
  projectId = null,
  isWorking = false,
  desktopOverlay = true,
  desktopOverlayInner = false,
  embedded = false,
}: {
  workspace: string
  open: boolean
  initialTab?: 'files' | 'changed' | 'graph' | 'progress'
  onClose: () => void
  mobile?: boolean
  selectedFilePath?: string | null
  onFileSelect?: (file: WorkspaceFileInfo | null) => void
  sessionId?: string | null
  projectId?: string | null
  isWorking?: boolean
  /** Dock into AppShell's body row instead of covering it. */
  desktopOverlay?: boolean
  desktopOverlayInner?: boolean
  embedded?: boolean
}) {
  const preset = useMotionPreset()
  const [tab, setTab] = useState<'files' | 'changed' | 'graph' | 'progress'>(initialTab)
  const [scOpen, setScOpen] = useState(false)
  const [scWorkspace, setScWorkspace] = useState('')
  const projectQuery = useProjectQuery(projectId)
  const project = projectQuery.data ?? null
  // Drive multi/single-repo mode off the *primed* projectId, not the async
  // project fetch — otherwise the single-workspace diff flashes while the
  // project detail is still loading (see forge.tsx projectId priming).
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
  const fileByPath = new Map((files.data?.files ?? []).map((file) => [file.path, file]))

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
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-(--color-border) px-4 py-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-(--color-text)">
              {isProjectMode ? 'Project' : 'Workspace'}
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
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Close workspace panel"
            title="Close"
          >
            <X size={16} />
          </button>
        </header>
        <div className="border-b border-(--color-border) p-1">
          <div className="relative grid grid-cols-4 items-center rounded-lg border border-(--color-border) bg-(--bg-page) p-0.5">
            <motion.div
              aria-hidden="true"
              className="pointer-events-none absolute bottom-0.5 left-0.5 top-0.5 w-[calc((100%-0.25rem)/4)] rounded-md bg-(--bg-key) shadow-sm"
              initial={false}
              animate={{ x: `${WORKSPACE_TABS.findIndex((t) => t.key === tab) * 100}%` }}
              transition={preset.spring}
            />
            {WORKSPACE_TABS.map(({ key, label, Icon }) => {
              const active = tab === key
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => setTab(key)}
                  title={label}
                  className={cn(
                    'relative z-10 flex min-w-0 items-center justify-center gap-1 rounded-md px-1 py-1.5 text-xs outline-none transition-[color,transform] duration-(--motion-fast) active:translate-y-px focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-(--color-accent)/35',
                    active ? 'font-medium text-(--color-text)' : 'text-(--color-text-muted) hover:text-(--color-text-2)',
                  )}
                >
                  <Icon size={13} className="shrink-0" aria-hidden="true" />
                  <span className="truncate">{key === 'changed' ? 'Source' : label}</span>
                  {key === 'changed' && !isProjectMode && changedPaths.size > 0 && (
                    <span className="rounded-full bg-(--color-warning)/15 px-1 py-px font-mono text-[10px] text-(--accent-orange-text)">{changedPaths.size}</span>
                  )}
                </button>
              )
            })}
          </div>
        </div>
        {tab === 'graph' ? (
          <div className="flex min-h-0 flex-1 flex-col">
            {isProjectMode ? (
              project ? (
                <>
                  <div className="shrink-0 border-b border-(--color-border) p-2">
                    <CrossRepoLinksPanel project={project} />
                  </div>
                  <div className="min-h-0 flex-1">
                    <ProjectCodeGraphPanel project={project} onFileSelect={onFileSelect} />
                  </div>
                </>
              ) : (
                <p className="px-2 py-4 text-xs text-(--color-text-subtle)">Loading project repositories…</p>
              )
            ) : (
              <div className="min-h-0 flex-1">
                <CodeGraphPanel workspace={workspace} onFileSelect={onFileSelect} />
              </div>
            )}
          </div>
        ) : tab === 'progress' ? (
          <div className="min-h-0 flex-1 overflow-auto py-2">
            <TaskTimelinePanel sessionId={sessionId} isWorking={isWorking} />
          </div>
        ) : (
          <>
        <div className={cn('min-h-0 flex-1 overflow-auto', tab === 'files' && 'p-2')}>
          {tab === 'changed' ? (
            isProjectMode ? (
              project ? (
                <DiffReviewPanel
                  project={project}
                  className="p-2"
                  onOpenRepo={(path) => { setScWorkspace(path); setScOpen(true) }}
                />
              ) : (
                <p className="px-2 py-4 text-xs text-(--color-text-subtle)">Loading project repositories…</p>
              )
            ) : diff.isLoading || files.isLoading ? (
              <p className="px-2 py-4 text-xs text-(--color-text-subtle)">Loading changed files…</p>
            ) : diff.isError ? (
              <p className="px-2 py-4 text-xs text-(--color-error)">Failed to load changed files</p>
            ) : !diff.data?.is_git_repo ? (
              <p className="px-2 py-4 text-xs text-(--color-text-subtle)">Not a git repository</p>
            ) : (
              <div className="p-2">
                <button
                  type="button"
                  onClick={() => { setScWorkspace(workspace); setScOpen(true) }}
                  className="mb-2 flex w-full items-center justify-center gap-1.5 rounded-md border border-(--color-border) bg-(--bg-key) px-2 py-1.5 text-xs text-(--color-text) hover:bg-(--bg-key)/70"
                >
                  <GitBranch size={12} /> Open Source Control
                </button>
                {diff.data.truncated && <p className="mb-2 rounded bg-(--color-warning)/10 px-2 py-1 text-xs text-(--color-warning)">Changed list may be incomplete because the diff was truncated.</p>}
                <div className="space-y-1">
                  {changedFiles.map((changedFile) => {
                    const file = fileByPath.get(changedFile.path) ?? { path: changedFile.path, name: changedFile.path.split('/').pop() ?? changedFile.path, size: 0, mtime: 0, mime: 'text/plain' }
                    const isSelected = selectedFilePath === changedFile.path
                    return (
                      <button
                        key={changedFile.path}
                        type="button"
                        onClick={() => onFileSelect?.(isSelected ? null : file)}
                        className={cn(
                          'flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors',
                          isSelected ? 'bg-(--bg-key) text-(--color-accent)' : 'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)',
                        )}
                        title={changedFile.path}
                      >
                        <FileText size={12} className="shrink-0 text-(--accent-orange-text)" />
                        <span className="min-w-0 flex-1 truncate font-mono">{changedFile.path}</span>
                        <span className="shrink-0 font-mono text-xs text-(--color-diff-add-text)">{changedFile.additions > 0 ? `+${changedFile.additions}` : ''}</span>
                        <span className="shrink-0 font-mono text-xs text-(--color-diff-del-text)">{changedFile.deletions > 0 ? `-${changedFile.deletions}` : ''}</span>
                        <span className="shrink-0 font-mono text-xs font-semibold text-(--accent-orange-text)" aria-label={CHANGED_STATUS_LABELS[changedFile.status]}>{changedFile.status}</span>
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          ) : isProjectMode ? (
            project ? (
              <MultiRepoFileTree project={project} selectedFilePath={selectedFilePath} onFileSelect={onFileSelect} />
            ) : (
              <p className="px-2 py-4 text-xs text-(--color-text-subtle)">Loading project repositories…</p>
            )
          ) : (
            files.isLoading ? (
              <p className="px-2 py-4 text-xs text-(--color-text-subtle)">Loading files…</p>
            ) : files.isError ? (
              <p className="px-2 py-4 text-xs text-(--color-error)">Failed to load files</p>
            ) : files.data?.files.length === 0 ? (
              <p className="px-2 py-4 text-xs text-(--color-text-subtle)">No files shown</p>
            ) : isTauriAvailable() ? (
              // Native file tree (desktop-only, lazy loading)
              <NativeFileTree
                workspaceRoot={workspace}
                selectedPath={selectedFilePath}
                onFileSelect={(entry) => {
                  if (!entry) {
                    onFileSelect?.(null)
                    return
                  }
                  // Convert DirEntry to WorkspaceFileInfo for compatibility
                  onFileSelect?.({
                    path: entry.path,
                    name: entry.name,
                    size: entry.size,
                    mtime: entry.mtime,
                    mime: entry.mime,
                  })
                }}
                className="flex-1 overflow-auto"
              />
            ) : (
              // Web fallback: HTTP-based tree
              <div className="p-2">
                {(files.data?.files ?? []).length === 0
                  ? <p className="px-2 py-4 text-xs text-(--color-text-subtle)">No files shown</p>
                  : Array.from(buildTree(files.data?.files ?? []).children.values()).map((node) => (
                      <TreeNodeView
                        key={node.path}
                        node={node}
                        depth={0}
                        selectedPath={selectedFilePath}
                        onFileSelect={onFileSelect}
                        changedPaths={changedPaths}
                      />
                    ))
                }
              </div>
            )
          )}
        </div>
        {!isProjectMode && (
          <button type="button" onClick={() => { void files.refetch(); void diff.refetch() }} className="flex items-center justify-center gap-1.5 border-t border-(--color-border) px-3 py-2 text-xs text-(--color-text-muted) hover:bg-(--bg-key)">
            <RefreshCw size={12} /> Refresh
          </button>
        )}
          </>
        )}
      <SourceControlModal
        open={scOpen}
        onOpenChange={setScOpen}
        workspace={scWorkspace || workspace}
        onWorkspaceChange={setScWorkspace}
        project={project}
      />
    </SidePanel>
  )
}
