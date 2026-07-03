/**
 * MultiRepoFileTree — file browser for CodingProject sessions.
 *
 * Mirrors DiffReviewPanel's per-repo grouping: one collapsible section per
 * project repo, each with its own file tree. Exists because the Files tab
 * previously fell back to the session's single primary workspace even in
 * project mode, silently showing only one of the project's repos.
 */

import { useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Folder, Loader2 } from 'lucide-react'
import { getCodingWorkspaceGitDiff, listCodingWorkspaceFiles } from '@/api/client'
import { queryKeys } from '@/queries/keys'
import { cn } from '@/lib/utils'
import { TreeNodeView } from './CodingWorkspacePanel'
import { buildTree, collectChangedFiles } from '@/utils/workspaceFileTree'
import type { CodingProject, WorkspaceFileInfo } from '@/api/types'

function repoLabel(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

export interface MultiRepoFileTreeProps {
  project: CodingProject
  selectedFilePath?: string | null
  onFileSelect?: (file: WorkspaceFileInfo | null) => void
  className?: string
}

export function MultiRepoFileTree({ project, selectedFilePath = null, onFileSelect, className }: MultiRepoFileTreeProps) {
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
    <div className={cn('flex flex-col gap-2', className)}>
      {project.workspaces.map((w, i) => {
        const files = filesQueries[i]
        const diff = diffQueries[i]
        // Tag each file with its repo's absolute path so selecting a file
        // from a non-primary repo opens the right workspace in the viewer
        // (WorkspaceFileInfo.path alone is repo-relative and ambiguous
        // across repos — see WorkspaceFileInfo.sourceWorkspace).
        const taggedFiles = (files.data?.files ?? []).map((f) => ({ ...f, sourceWorkspace: w.path }))
        const tree = buildTree(taggedFiles)
        const changedPaths = new Set(collectChangedFiles(diff.data).map((f) => f.path))
        const isCollapsed = collapsedPaths.has(w.path)
        const name = w.display_name || w.name || repoLabel(w.path)

        return (
          <div key={w.workspace_id} className="overflow-hidden rounded-md border border-(--color-border)">
            <button
              type="button"
              onClick={() => toggleCollapsed(w.path)}
              className="flex w-full items-center gap-2 border-b border-(--color-border) bg-(--bg-subtle) px-3 py-1.5 text-left"
              aria-expanded={!isCollapsed}
            >
              {isCollapsed ? (
                <ChevronRight size={12} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
              ) : (
                <ChevronDown size={12} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
              )}
              <Folder size={12} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
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
                  {files.data?.files.length ?? 0}
                </span>
              )}
            </button>
            {!isCollapsed && (
              <div className="p-2">
                {files.isLoading ? (
                  <p className="px-2 py-2 text-xs text-(--color-text-subtle)">Loading files…</p>
                ) : files.isError ? (
                  <p className="px-2 py-2 text-xs text-(--color-error)">Failed to load files</p>
                ) : taggedFiles.length === 0 ? (
                  <p className="px-2 py-2 text-xs text-(--color-text-subtle)">No files</p>
                ) : (
                  <TreeNodeView node={tree} depth={0} selectedPath={selectedFilePath} onFileSelect={onFileSelect} changedPaths={changedPaths} />
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
