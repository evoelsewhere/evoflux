/**
 * WorkspaceInfoCard — coding-mode empty-state placeholder.
 *
 * Rendered inside ``AgentView`` (via the ``emptyState`` slot) when the user
 * is in coding mode and hasn't sent a message yet. Replaces the generic
 * "what's on your mind?" mascot with concrete context about the workspace
 * the agent is bound to: name, path, git branch, dirty counts, last commit.
 *
 * Backed by ``GET /api/team/workspace/status``. Fetched once on mount;
 * manual refresh via the button — no polling.
 */

import { useQuery } from '@tanstack/react-query'
import { formatDistanceToNowStrict } from 'date-fns'
import { motion } from 'framer-motion'
import { Folder, GitBranch } from 'lucide-react'

import { getCodingWorkspaceStatus } from '@/api/client'
import { fadeRise, useMotionPreset } from '@/lib/motion'
import { queryKeys } from '@/queries'

interface Props {
  workspace: string
}

export function WorkspaceInfoCard({ workspace }: Props) {
  const preset = useMotionPreset()
  const enter = fadeRise(preset, 10)
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.coding.status(workspace),
    queryFn: () => getCodingWorkspaceStatus(workspace),
    // Workspace status is informational and can be reused across route
    // transitions; cache briefly to avoid duplicate git status probes when
    // coding views remount for the same workspace.
    staleTime: 30_000,
  })

  const name = data?.name ?? workspace.split('/').filter(Boolean).pop() ?? workspace
  const dirty = data?.dirty
  const dirtyTotal = dirty ? dirty.staged + dirty.unstaged + dirty.untracked : 0

  return (
    <motion.div
      initial={enter.initial}
      animate={enter.animate}
      transition={enter.transition}
      className="mx-auto w-full max-w-md rounded-xl bg-(--bg-card) px-4 py-4"
    >
      <div className="flex min-w-0 items-center gap-2">
        <Folder size={16} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
        <h2 className="truncate text-sm font-semibold text-(--color-text)" title={name}>
          {name}
        </h2>
      </div>

      <p
        className="mt-1 truncate font-mono text-xs text-(--color-text-subtle)"
        title={workspace}
      >
        {workspace}
      </p>

      {isLoading ? (
        <p className="mt-3 text-xs text-(--color-text-muted)">Loading…</p>
      ) : data?.is_git_repo ? (
        <div className="mt-3 space-y-2 text-xs">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {data.branch && (
              <span
                className="inline-flex items-center gap-1 text-(--color-text-2)"
                title="Current branch"
              >
                <GitBranch size={11} aria-hidden="true" />
                <span className="font-mono">{data.branch}</span>
              </span>
            )}
            {dirty && dirtyTotal > 0 ? (
              <span className="font-mono text-(--color-text-muted)" title="staged · unstaged · untracked">
                {dirty.staged > 0 && <span className="text-(--color-success)">+{dirty.staged}</span>}
                {dirty.staged > 0 && (dirty.unstaged > 0 || dirty.untracked > 0) && ' '}
                {dirty.unstaged > 0 && <span className="text-(--color-warning)">~{dirty.unstaged}</span>}
                {dirty.unstaged > 0 && dirty.untracked > 0 && ' '}
                {dirty.untracked > 0 && <span className="text-(--color-text-subtle)">?{dirty.untracked}</span>}
              </span>
            ) : (
              <span className="text-(--color-text-subtle)">clean</span>
            )}
          </div>

          {data.head && (
            <div className="flex items-baseline gap-2 text-(--color-text-muted)">
              <span className="font-mono text-(--color-text-2)">{data.head.sha}</span>
              <span className="min-w-0 flex-1 truncate" title={data.head.subject}>
                {data.head.subject}
              </span>
              <span
                className="shrink-0 text-(--color-text-subtle)"
                title={new Date(data.head.timestamp * 1000).toLocaleString()}
              >
                {formatDistanceToNowStrict(new Date(data.head.timestamp * 1000), { addSuffix: true })}
              </span>
            </div>
          )}
        </div>
      ) : (
        <p className="mt-3 text-xs text-(--color-text-muted)">Not a git repository</p>
      )}
    </motion.div>
  )
}
