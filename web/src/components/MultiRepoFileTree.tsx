/**
 * MultiRepoFileTree — file browser for CodingProject sessions.
 *
 * Presents every project repository as a top-level folder in one continuous
 * tree. Exists because the Files tab previously fell back to the session's
 * single primary workspace even in project mode, silently showing only one of
 * the project's repos.
 */

import { useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react'
import { getCodingWorkspaceGitDiff, listCodingWorkspaceFiles } from '@/api/client'
import { queryKeys } from '@/queries/keys'
import { cn } from '@/lib/utils'
import { TreeNodeView } from './CodingWorkspacePanel'
import { buildTree, collectChangedFiles } from '@/utils/workspaceFileTree'
import type { CodingProject, WorkspaceFileInfo } from '@/api/types'
import { FolderTypeIcon } from './FileTypeIcon'

function repoLabel(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

export interface MultiRepoFileTreeProps {
  project: CodingProject
  selectedFilePath?: string | null
  selectedSourceWorkspace?: string | null
  onFileSelect?: (file: WorkspaceFileInfo | null) => void
  onFileOpen?: (file: WorkspaceFileInfo) => void
  searchQuery?: string
  className?: string
}

export function MultiRepoFileTree({
  project,
  selectedFilePath = null,
  selectedSourceWorkspace = null,
  onFileSelect,
  onFileOpen,
  searchQuery = '',
  className,
}: MultiRepoFileTreeProps) {
  const paths = project.workspaces.map((w) => w.path)
  const [collapsedPaths, setCollapsedPaths] = useState<Set<string>>(() => new Set())

  const filesQueries = useQueries({
    queries: paths.map((path) => ({
      queryKey: queryKeys.coding.files(path),
      queryFn: () => listCodingWorkspaceFiles(path),
      staleTime: 5_000,
    })),
  })
  // Reuses DiffReviewPanel's query key/cache — reading it here just to mark
  // changed files in the tree costs no extra network round-trip when the
  // Changed tab has already populated the cache for the same repo.
  const diffQueries = useQueries({
    queries: paths.map((path) => ({
      queryKey: queryKeys.coding.diff(path),
      queryFn: () => getCodingWorkspaceGitDiff(path),
      staleTime: 5_000,
    })),
  })

  if (paths.length === 0) {
    return (
      <p className={cn('px-2 py-4 text-xs text-(--color-text-subtle)', className)}>
        No repositories in this project.
      </p>
    )
  }

  const toggleCollapsed = (path: string) => {
    setCollapsedPaths((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  return (
    <div className={cn('flex flex-col', className)}>
      {project.workspaces.map((w, i) => {
        const files = filesQueries[i]
        const diff = diffQueries[i]
        // Tag each file with its repo's absolute path so selecting a file
        // from a non-primary repo opens the right workspace in the viewer
        // (WorkspaceFileInfo.path alone is repo-relative and ambiguous
        // across repos — see WorkspaceFileInfo.sourceWorkspace).
        const taggedFiles = (files.data?.files ?? []).map((f) => ({ ...f, sourceWorkspace: w.path }))
        const normalizedQuery = searchQuery.trim().toLowerCase()
        const visibleFiles = normalizedQuery
          ? taggedFiles.filter((file) => file.path.toLowerCase().includes(normalizedQuery))
          : taggedFiles
        const tree = buildTree(visibleFiles)
        const changedPaths = new Set(collectChangedFiles(diff.data).map((f) => f.path))
        const isCollapsed = normalizedQuery ? false : collapsedPaths.has(w.path)
        const name = w.display_name || w.name || repoLabel(w.path)

        return (
          <div key={w.workspace_id}>
            <button
              type="button"
              onClick={() => toggleCollapsed(w.path)}
              className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-xs text-(--color-text) hover:bg-(--bg-key)"
              aria-expanded={!isCollapsed}
            >
              {isCollapsed ? (
                <ChevronRight size={12} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
              ) : (
                <ChevronDown size={12} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
              )}
              <FolderTypeIcon open={!isCollapsed} size={16} />
              <span className="flex-1 truncate text-xs font-medium text-(--color-text)">{name}</span>
              {files.isLoading && <Loader2 size={11} className="animate-spin text-(--color-text-muted)" aria-hidden="true" />}
              {files.isError && (
                <span
                  className="text-[10px] text-red-400"
                  title={files.error instanceof Error ? files.error.message : 'Failed to load files'}
                >
                  failed
                </span>
              )}
              {!files.isLoading && !files.isError && (
                <span className="rounded-full bg-(--bg-key) px-1.5 py-0.5 text-[10px] text-(--color-text-muted)">
                  {normalizedQuery
                    ? `${visibleFiles.length}/${taggedFiles.length}`
                    : taggedFiles.length}
                </span>
              )}
            </button>
            {!isCollapsed && (
              <div>
                {files.isLoading ? (
                  <p className="py-2 pl-8 pr-2 text-xs text-(--color-text-subtle)">Loading files…</p>
                ) : files.isError ? (
                  <p className="py-2 pl-8 pr-2 text-xs text-(--color-error)">Failed to load files</p>
                ) : visibleFiles.length === 0 ? (
                  <p className="py-2 pl-8 pr-2 text-xs text-(--color-text-subtle)">
                    {normalizedQuery ? 'No matching files' : 'No files'}
                  </p>
                ) : (
                  Array.from(tree.children.values()).map((node) => (
                    <TreeNodeView
                      key={node.path}
                      node={node}
                      depth={1}
                      selectedPath={selectedFilePath}
                      selectedSourceWorkspace={selectedSourceWorkspace}
                      onFileSelect={onFileSelect}
                      onFileOpen={onFileOpen}
                      changedPaths={changedPaths}
                      forceOpen={Boolean(normalizedQuery)}
                    />
                  ))
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
