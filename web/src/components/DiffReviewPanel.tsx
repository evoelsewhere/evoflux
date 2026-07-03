/**
 * DiffReviewPanel — cross-repo diff overview for CodingProject sessions.
 *
 * Shows all changed files across every repo in the project, grouped by
 * workspace. Provides a "Create PRs" shortcut that instructs the agent to
 * commit and open pull requests for each dirty repo.
 *
 * Intended for the coding workspace side-panel when a session has a project.
 */

import { useMemo } from 'react'
import { useQueries } from '@tanstack/react-query'
import {
  GitBranch,
  RefreshCw,
  SquarePlus,
  Loader2,
  AlertCircle,
  FileCode2,
  Plus,
  Minus,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { getCodingWorkspaceGitDiff } from '@/api/client'
import { queryKeys } from '@/queries/keys'
import { useTeamStore } from '@/stores/useTeamStore'
import type { CodingProject } from '@/api/types'
import type { WorkspaceGitDiffResponse } from '@/api/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

interface ChangedFile {
  path: string
  status: 'A' | 'M' | 'D'
  additions: number
  deletions: number
}

function parseChangedFiles(diff?: WorkspaceGitDiffResponse): ChangedFile[] {
  const files = new Map<string, ChangedFile>()
  if (!diff?.is_git_repo || !diff.diff) return []

  let current: ChangedFile | null = null
  for (const line of diff.diff.split('\n')) {
    if (line.startsWith('diff --git ')) {
      const match = /^diff --git a\/(.*) b\/(.*)$/.exec(line)
      if (!match?.[2]) { current = null; continue }
      current = files.get(match[2]) ?? { path: match[2], status: 'M', additions: 0, deletions: 0 }
      files.set(current.path, current)
      continue
    }
    if (!current) continue
    if (line.startsWith('new file mode')) current.status = 'A'
    else if (line.startsWith('deleted file mode')) current.status = 'D'
    else if (line.startsWith('+') && !line.startsWith('+++')) current.additions += 1
    else if (line.startsWith('-') && !line.startsWith('---')) current.deletions += 1
  }
  for (const path of diff.untracked ?? []) {
    if (!files.has(path)) files.set(path, { path, status: 'A', additions: 0, deletions: 0 })
  }
  return Array.from(files.values()).sort((a, b) => a.path.localeCompare(b.path))
}

function repoLabel(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

function statusBadge(status: 'A' | 'M' | 'D') {
  if (status === 'A') return (
    <span className="rounded px-0.5 text-[9px] font-bold uppercase text-green-400">A</span>
  )
  if (status === 'D') return (
    <span className="rounded px-0.5 text-[9px] font-bold uppercase text-red-400">D</span>
  )
  return (
    <span className="rounded px-0.5 text-[9px] font-bold uppercase text-amber-400">M</span>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export interface DiffReviewPanelProps {
  project?: CodingProject | null
  workspacePaths?: string[]
  className?: string
  onOpenRepo?: (path: string) => void
}

export function DiffReviewPanel({ project, workspacePaths, className, onOpenRepo }: DiffReviewPanelProps) {
  const paths = useMemo(() => {
    if (project) return project.workspaces.map((w) => w.path)
    return workspacePaths ?? []
  }, [project, workspacePaths])

  const repoNames = useMemo(() => {
    if (project) {
      const map = new Map<string, string>()
      for (const w of project.workspaces) {
        map.set(w.path, w.display_name || w.name || repoLabel(w.path))
      }
      return map
    }
    return new Map(paths.map((p) => [p, repoLabel(p)]))
  }, [project, paths])

  const queries = useQueries({
    queries: paths.map((path) => ({
      queryKey: queryKeys.coding.diff(path),
      queryFn: () => getCodingWorkspaceGitDiff(path),
      staleTime: 15_000,
      enabled: true,
    })),
  })

  const anyLoading = queries.some((q) => q.isLoading)

  const refetchAll = () => {
    for (const q of queries) void q.refetch()
  }

  // Build repo → file[] map
  const repoFiles = useMemo(() => {
    return paths.map((path, i) => ({
      path,
      name: repoNames.get(path) ?? repoLabel(path),
      files: parseChangedFiles(queries[i]?.data),
      isLoading: queries[i]?.isLoading,
      isError: queries[i]?.isError,
      error: queries[i]?.error,
      // Default to true while loading so we don't flash "not a git repo".
      isGitRepo: queries[i]?.data?.is_git_repo ?? true,
      isDirty: (queries[i]?.data?.diff?.length ?? 0) > 0 || (queries[i]?.data?.untracked?.length ?? 0) > 0,
    }))
  }, [paths, repoNames, queries])

  const totalFiles = repoFiles.reduce((n, r) => n + r.files.length, 0)
  const dirtyRepos = repoFiles.filter((r) => r.isDirty)

  const handleCreatePRs = () => {
    if (dirtyRepos.length === 0) return
    const repoPaths = dirtyRepos.map((r) => `- ${r.name} (\`${r.path}\`)`).join('\n')
    const message = [
      `Please commit all changes and create pull requests for the following repositories:`,
      repoPaths,
      '',
      `For each repo: stage everything (\`git add -A\`), commit with a descriptive message, push, and run \`create_pull_request\`.`,
      `Use the session chapters as context for the PR title and body.`,
    ].join('\n')
    void useTeamStore.getState().sendMessage(message)
  }

  if (paths.length === 0) {
    return (
      <div className={cn('flex flex-col items-center justify-center py-12 text-center', className)}>
        <GitBranch size={24} className="mb-2 text-(--color-text-muted) opacity-40" />
        <p className="text-xs text-(--color-text-muted)">No repositories in this project.</p>
      </div>
    )
  }

  return (
    <div className={cn('flex flex-col gap-2', className)}>
      {/* Header */}
      <div className="flex items-center justify-between px-1">
        <span className="text-xs font-medium text-(--color-text-muted)">
          {totalFiles} changed {totalFiles === 1 ? 'file' : 'files'} across {dirtyRepos.length}/{paths.length} repos
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={refetchAll}
            disabled={anyLoading}
            className="flex h-6 w-6 items-center justify-center rounded text-(--color-text-muted) hover:bg-(--bg-hover) hover:text-(--color-text) disabled:opacity-50"
            title="Refresh"
          >
            <RefreshCw size={11} className={anyLoading ? 'animate-spin' : ''} />
          </button>
          {dirtyRepos.length > 0 && (
            <button
              type="button"
              onClick={handleCreatePRs}
              className={cn(
                'flex items-center gap-1 rounded-md px-2 py-1',
                'bg-(--accent-blue) text-white text-xs font-medium',
                'hover:bg-(--accent-blue)/90 transition-colors',
              )}
              title="Commit and open PRs for all dirty repos"
            >
              <SquarePlus size={11} />
              Create PRs
            </button>
          )}
        </div>
      </div>

      {/* Per-repo sections */}
      <div className="space-y-2">
        {repoFiles.map((repo) => (
          <div
            key={repo.path}
            className="rounded-md border border-(--color-border) overflow-hidden"
          >
            {/* Repo header */}
            {onOpenRepo ? (
              <button
                type="button"
                onClick={() => onOpenRepo(repo.path)}
                className={cn(
                  'flex w-full items-center gap-2 px-3 py-1.5',
                  'bg-(--bg-subtle) border-b border-(--color-border)',
                  'hover:bg-(--bg-key) transition-colors text-left',
                )}
              >
                <GitBranch size={12} className="shrink-0 text-(--color-text-muted)" />
                <span className="flex-1 truncate text-xs font-medium text-(--color-text)">
                  {repo.name}
                </span>
                {repo.isLoading && <Loader2 size={11} className="animate-spin text-(--color-text-muted)" />}
                {repo.isError && (
                  <span
                    className="flex items-center gap-1 text-[10px] text-red-400"
                    title={repo.error instanceof Error ? repo.error.message : 'Failed to load diff'}
                  >
                    <AlertCircle size={11} />
                    failed
                  </span>
                )}
                {!repo.isLoading && !repo.isError && !repo.isGitRepo && (
                  <span className="text-[10px] text-amber-400" title="This workspace is not a git repository">
                    not a git repo
                  </span>
                )}
                {!repo.isLoading && !repo.isError && repo.isGitRepo && repo.files.length === 0 && (
                  <span className="text-[10px] text-(--color-text-muted)">clean</span>
                )}
                {repo.files.length > 0 && (
                  <span className="rounded-full bg-(--bg-key) px-1.5 py-0.5 text-[10px] text-(--color-text-muted)">
                    {repo.files.length}
                  </span>
                )}
              </button>
            ) : (
              <div
                className={cn(
                  'flex items-center gap-2 px-3 py-1.5',
                  'bg-(--bg-subtle) border-b border-(--color-border)',
                )}
              >
              <GitBranch size={12} className="shrink-0 text-(--color-text-muted)" />
              <span className="flex-1 truncate text-xs font-medium text-(--color-text)">
                {repo.name}
              </span>
              {repo.isLoading && <Loader2 size={11} className="animate-spin text-(--color-text-muted)" />}
              {repo.isError && (
                <span
                  className="flex items-center gap-1 text-[10px] text-red-400"
                  title={repo.error instanceof Error ? repo.error.message : 'Failed to load diff'}
                >
                  <AlertCircle size={11} />
                  failed
                </span>
              )}
              {!repo.isLoading && !repo.isError && !repo.isGitRepo && (
                <span className="text-[10px] text-amber-400" title="This workspace is not a git repository">
                  not a git repo
                </span>
              )}
              {!repo.isLoading && !repo.isError && repo.isGitRepo && repo.files.length === 0 && (
                <span className="text-[10px] text-(--color-text-muted)">clean</span>
              )}
              {repo.files.length > 0 && (
                <span className="rounded-full bg-(--bg-key) px-1.5 py-0.5 text-[10px] text-(--color-text-muted)">
                  {repo.files.length}
                </span>
              )}
            </div>
            )}

            {/* File list */}
            {repo.files.length > 0 && (
              <div className="divide-y">
                {repo.files.map((file) => (
                  <div
                    key={file.path}
                    className="flex items-center gap-2 px-3 py-1.5 hover:bg-(--bg-hover)"
                  >
                    <FileCode2 size={11} className="shrink-0 text-(--color-text-muted)" />
                    <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-(--color-text)">
                      {file.path}
                    </span>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {statusBadge(file.status)}
                      {file.additions > 0 && (
                        <span className="flex items-center gap-0.5 text-[10px] text-green-400">
                          <Plus size={9} />{file.additions}
                        </span>
                      )}
                      {file.deletions > 0 && (
                        <span className="flex items-center gap-0.5 text-[10px] text-red-400">
                          <Minus size={9} />{file.deletions}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
