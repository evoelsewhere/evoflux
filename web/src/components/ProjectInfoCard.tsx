/**
 * ProjectInfoCard — coding-mode empty-state placeholder for PROJECT sessions.
 *
 * Project counterpart to WorkspaceInfoCard: a project session isn't "in" any
 * one repo, so this shows the project identity (name, repo count) and a
 * compact per-repo status line for each member repo, instead of one repo's
 * branch/dirty/last-commit.
 */

import { useQueries } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { FolderPlus, GitBranch } from 'lucide-react'

import { getCodingWorkspaceStatus } from '@/api/client'
import { fadeRise, useMotionPreset } from '@/lib/motion'
import { queryKeys } from '@/queries'
import type { CodingProject } from '@/api/types'

interface Props {
  project: CodingProject
}

function repoLabel(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

export function ProjectInfoCard({ project }: Props) {
  const preset = useMotionPreset()
  const enter = fadeRise(preset, 10)
  const statusQueries = useQueries({
    queries: project.workspaces.map((w) => ({
      queryKey: queryKeys.coding.status(w.path),
      queryFn: () => getCodingWorkspaceStatus(w.path),
      staleTime: 30_000,
    })),
  })

  return (
    <motion.div
      initial={enter.initial}
      animate={enter.animate}
      transition={enter.transition}
      className="mx-auto w-full max-w-md rounded-xl bg-(--bg-card) px-4 py-4"
    >
      <div className="flex min-w-0 items-center gap-2">
        <FolderPlus size={16} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
        <h2 className="truncate text-sm font-semibold text-(--color-text)" title={project.name}>
          {project.name}
        </h2>
        <span className="shrink-0 rounded-full bg-(--bg-key) px-1.5 py-0.5 text-[10px] text-(--color-text-muted)">
          {project.workspaces.length} {project.workspaces.length === 1 ? 'repo' : 'repos'}
        </span>
      </div>

      {project.workspaces.length === 0 ? (
        <p className="mt-3 text-xs text-(--color-text-muted)">No repositories yet.</p>
      ) : (
        <div className="mt-3 space-y-1.5">
          {project.workspaces.map((w, i) => {
            const status = statusQueries[i]
            const name = w.display_name || w.name || status.data?.name || repoLabel(w.path)
            const dirty = status.data?.dirty
            const dirtyTotal = dirty ? dirty.staged + dirty.unstaged + dirty.untracked : 0
            return (
              <div key={w.workspace_id} className="flex min-w-0 items-center gap-2 text-xs">
                <span className="min-w-0 flex-1 truncate text-(--color-text-2)" title={w.path}>
                  {name}
                </span>
                {status.isLoading ? (
                  <span className="shrink-0 text-(--color-text-subtle)">…</span>
                ) : status.data?.is_git_repo === false ? (
                  <span className="shrink-0 text-(--color-text-subtle)">not a git repo</span>
                ) : (
                  <span className="flex shrink-0 items-center gap-2 font-mono text-(--color-text-muted)">
                    {status.data?.branch && (
                      <span className="inline-flex items-center gap-1" title="Current branch">
                        <GitBranch size={10} aria-hidden="true" />
                        {status.data.branch}
                      </span>
                    )}
                    {dirtyTotal > 0 ? (
                      <span title="staged · unstaged · untracked">
                        {dirty!.staged > 0 && <span className="text-(--color-success)">+{dirty!.staged}</span>}
                        {dirty!.unstaged > 0 && <span className="text-(--color-warning)"> ~{dirty!.unstaged}</span>}
                        {dirty!.untracked > 0 && <span className="text-(--color-text-subtle)"> ?{dirty!.untracked}</span>}
                      </span>
                    ) : (
                      <span className="text-(--color-text-subtle)">clean</span>
                    )}
                  </span>
                )}
              </div>
            )
          })}
        </div>
      )}
    </motion.div>
  )
}
