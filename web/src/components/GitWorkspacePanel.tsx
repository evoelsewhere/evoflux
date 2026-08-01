import { useMemo, useState } from 'react'
import { GitBranch } from 'lucide-react'

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
  type GitWorkspaceView,
  type PullRequestsScope,
} from '@/stores/useUIStore'
import { workspaceLabel } from '@/utils/workspace'
import { PullRequestsPanel } from './PullRequestsPanel'
import { SourceControlPanel } from './SourceControlModal'

interface GitWorkspacePanelProps {
  open: boolean
  view: GitWorkspaceView
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
 * Shared content for the top-level Changes and Review Workbench tabs.
 * `view` is fixed per tab, so this surface no longer renders a nested tablist.
 */
export function GitWorkspacePanel({
  open,
  view,
  scope,
  workspace,
  projectId,
  focus,
  onOpenInChat,
}: GitWorkspacePanelProps) {
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

      </header>

      <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
        {view === 'changes' ? (
          workspace ? (
            <SourceControlPanel
              open={open}
              workspace={gitWorkspace || workspace}
              onWorkspaceChange={setSelectedGitWorkspace}
              project={project}
              credentialLabel={credentialLabel}
            />
          ) : (
            <div className="flex h-full min-h-0 flex-col items-center justify-center gap-2 px-6 text-center">
              <GitBranch size={18} className="text-(--color-text-muted)" aria-hidden />
              <p className="text-sm font-medium text-(--color-text)">No workspace open</p>
              <p className="max-w-xs text-xs text-(--color-text-muted)">
                Open a coding workspace to review and commit local changes.
              </p>
            </div>
          )
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
