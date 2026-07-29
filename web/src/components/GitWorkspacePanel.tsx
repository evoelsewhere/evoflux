import { useEffect, useMemo, useState } from 'react'
import { GitBranch, GitPullRequest } from 'lucide-react'

import type {
  CodeReviewItem,
  RepositoryCodeReviews,
} from '@/api/types'
import type { CodeReviewSessionContext } from '@/lib/code-review-session'
import {
  useCodeReviewsQuery,
  useGitServerConnectionsQuery,
} from '@/queries'
import { useProjectQuery } from '@/queries/useProjectsQuery'
import {
  type PullRequestsScope,
  useUIStore,
} from '@/stores/useUIStore'
import { cn } from '@/lib/utils'
import { workspaceLabel } from '@/utils/workspace'
import { PullRequestsPanel } from './PullRequestsPanel'
import { SourceControlPanel } from './SourceControlModal'

interface GitWorkspacePanelProps {
  open: boolean
  scope: PullRequestsScope
  workspace: string | null
  projectId: string | null
  focus: CodeReviewSessionContext | null
  onOpenInChat: (
    repository: RepositoryCodeReviews,
    item: CodeReviewItem,
  ) => Promise<void>
}

/**
 * One coding-mode home for local Git and remote code review. The selected
 * view lives in the shared UI store so entry points from changed files,
 * review sessions, the sidebar, and keyboard shortcuts all land predictably.
 */
export function GitWorkspacePanel({
  open,
  scope,
  workspace,
  projectId,
  focus,
  onOpenInChat,
}: GitWorkspacePanelProps) {
  const view = useUIStore((state) => state.gitWorkspaceView)
  const setView = useUIStore((state) => state.setGitWorkspaceView)
  const [selectedGitWorkspace, setSelectedGitWorkspace] = useState<string | null>(null)
  const project = useProjectQuery(projectId).data ?? null
  const gitWorkspace =
    selectedGitWorkspace
    && (
      selectedGitWorkspace === workspace
      || project?.workspaces.some((item) => item.path === selectedGitWorkspace)
    )
      ? selectedGitWorkspace
      : workspace ?? ''
  const reviewScope =
    scope === 'session'
      ? projectId
        ? { projectId }
        : { workspace }
      : {}
  const repositories = useCodeReviewsQuery(open, reviewScope)
  const connections = useGitServerConnectionsQuery(open)

  useEffect(() => {
    if (focus) setView('reviews')
  }, [focus, setView])

  const activeRepository = useMemo(
    () => repositories.data?.repositories.find(
      (repository) => repository.workspace === gitWorkspace,
    ) ?? null,
    [gitWorkspace, repositories.data?.repositories],
  )
  const activeConnection = useMemo(
    () => connections.data?.find(
      (connection) => connection.id === activeRepository?.connection_id,
    ) ?? null,
    [activeRepository?.connection_id, connections.data],
  )
  const credentialLabel = activeConnection?.has_token
    ? `${activeConnection.name} credential`
    : null

  const changesDisabled = !workspace

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col bg-(--bg-page)">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-(--color-border) bg-(--bg-card)/40 px-3">
        <span className="flex min-w-0 flex-1 items-center gap-2">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-(--color-accent)/10 text-(--color-accent)">
            <GitBranch size={14} />
          </span>
          <span
            className="min-w-0 truncate text-xs font-semibold text-(--color-text)"
            title={gitWorkspace || undefined}
          >
            {gitWorkspace ? workspaceLabel(gitWorkspace) : 'All repositories'}
          </span>
        </span>

        <div
          className="flex shrink-0 items-center gap-1"
          role="tablist"
          aria-label="Source Control workspace view"
        >
          <button
            type="button"
            role="tab"
            aria-selected={view === 'changes'}
            disabled={changesDisabled}
            onClick={() => setView('changes')}
            className={cn(
              'flex h-8 items-center justify-center gap-1.5 rounded-md px-2.5 text-[11px] font-medium transition-colors',
              view === 'changes'
                ? 'bg-(--color-accent)/10 text-(--color-accent)'
                : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
              changesDisabled && 'cursor-not-allowed opacity-40',
            )}
          >
            <GitBranch size={13} />
            Changes
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === 'reviews'}
            onClick={() => setView('reviews')}
            className={cn(
              'flex h-8 items-center justify-center gap-1.5 rounded-md px-2.5 text-[11px] font-medium transition-colors',
              view === 'reviews'
                ? 'bg-(--color-accent)/10 text-(--color-accent)'
                : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
            )}
          >
            <GitPullRequest size={13} />
            Pull requests
            {(repositories.data?.total ?? 0) > 0 && (
              <span className={cn(
                'rounded-full px-1.5 py-px font-mono text-[9px]',
                view === 'reviews'
                  ? 'bg-(--color-accent)/15 text-(--color-accent)'
                  : 'bg-(--bg-key) text-(--color-text-subtle)',
              )}>
                {repositories.data?.total}
              </span>
            )}
          </button>
        </div>
      </header>

      <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
        {view === 'changes' && workspace ? (
          <SourceControlPanel
            open={open}
            workspace={gitWorkspace || workspace}
            onWorkspaceChange={setSelectedGitWorkspace}
            project={project}
            credentialLabel={credentialLabel}
          />
        ) : (
          <PullRequestsPanel
            open={open}
            scope={scope}
            workspace={workspace}
            projectId={projectId}
            focus={focus}
            onOpenInChat={onOpenInChat}
          />
        )}
      </div>
    </div>
  )
}
