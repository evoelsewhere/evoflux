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
import { Folder, FolderPlus, GitBranch } from 'lucide-react'

import { getCodingWorkspaceStatus } from '@/api/client'
import { CodingPromptSuggestions } from '@/components/CodingPromptSuggestions'
import { fadeRise, useMotionPreset } from '@/lib/motion'
import { queryKeys } from '@/queries'
import type { CodingProject } from '@/api/types'

interface Props {
  project: CodingProject
  onSuggestion?: (suggestion: string) => void
}

const PROJECT_SUGGESTIONS = [
  'Map how these repositories work together',
  'Find cross-repository integration risks',
  'Review changes across all repositories',
  'Plan a coordinated implementation',
]

function repoLabel(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

export function ProjectInfoCard({ project, onSuggestion }: Props) {
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

      <p className="mt-1 text-xs text-(--color-text-subtle)">
        {project.description?.trim() ||
          `Shared coding context across ${project.workspaces.length} ${project.workspaces.length === 1 ? 'repository' : 'repositories'}.`}
      </p>

      <CodingPromptSuggestions
        suggestions={PROJECT_SUGGESTIONS}
        onSuggestion={onSuggestion}
      />

      {project.workspaces.length === 0 ? (
        <p className="mt-3 text-xs text-(--color-text-muted)">No repositories yet.</p>
      ) : (
        <div className="mt-3">
          <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-(--color-text-subtle)">
            <Folder size={11} aria-hidden="true" />
            Repositories
          </div>
          <div className="space-y-1.5">
          {project.workspaces.map((w, i) => {
            const status = statusQueries[i]
            const name = w.display_name || w.name || status.data?.name || repoLabel(w.path)
            const dirty = status.data?.dirty
            const dirtyTotal = dirty ? dirty.staged + dirty.unstaged + dirty.untracked : 0
            return (
              <div
                key={w.workspace_id}
                className="flex min-w-0 items-start gap-2 rounded-lg bg-(--bg-page)/55 px-2.5 py-2 text-xs"
              >
                <Folder
                  size={12}
                  className="mt-0.5 shrink-0 text-(--color-text-muted)"
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="min-w-0 flex-1 truncate font-medium text-(--color-text-2)" title={w.path}>
                      {name}
                    </span>
                    {status.isLoading ? (
                      <span className="shrink-0 text-(--color-text-subtle)">Loading…</span>
                    ) : status.data?.is_git_repo === false ? (
                      <span className="shrink-0 text-[10px] text-(--color-text-subtle)">not a git repo</span>
                    ) : (
                      <span className="flex min-w-0 shrink-0 items-center gap-2 font-mono text-[10px] text-(--color-text-muted)">
                        {status.data?.branch && (
                          <span className="inline-flex min-w-0 items-center gap-1" title="Current branch">
                            <GitBranch size={10} aria-hidden="true" />
                            <span className="max-w-24 truncate">{status.data.branch}</span>
                          </span>
                        )}
                        {dirtyTotal > 0 ? (
                          <span className="shrink-0" title="staged · unstaged · untracked">
                            {dirty!.staged > 0 && <span className="text-(--color-success)">+{dirty!.staged}</span>}
                            {dirty!.unstaged > 0 && <span className="text-(--color-warning)"> ~{dirty!.unstaged}</span>}
                            {dirty!.untracked > 0 && <span className="text-(--color-text-subtle)"> ?{dirty!.untracked}</span>}
                          </span>
                        ) : (
                          <span className="shrink-0 text-(--color-text-subtle)">clean</span>
                        )}
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 truncate font-mono text-[10px] text-(--color-text-subtle)" title={w.path}>
                    {w.path}
                  </p>
                </div>
              </div>
            )
          })}
          </div>
        </div>
      )}
    </motion.div>
  )
}
