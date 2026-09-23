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
import { cn } from '@/lib/utils'
import {
  type GitWorkspaceView,
  type PullRequestsScope,
  useUIStore,
} from '@/stores/useUIStore'
import { workspaceLabel } from '@/utils/workspace'
import { PullRequestsPanel } from './PullRequestsPanel'
import { SourceControlPanel } from './SourceControlModal'

const GIT_WORKSPACE_VIEWS: { value: GitWorkspaceView; label: string }[] = [
  { value: 'changes', label: 'Changes' },
  { value: 'reviews', label: 'Review' },
]

interface GitWorkspacePanelProps {
  open: boolean
  /** Pull-request listing scope for the Review view; Changes is always the session's. */
  scope: PullRequestsScope
  workspace: string | null
  projectId: string | null
  focus: CodeReviewSessionContext | null
  onOpenInChat: (
    repository: RepositoryCodeReviews,
    item: CodeReviewItem,
  ) => Promise<void>
  onOpenWorkspace?: () => void
}

/**
 * The Workbench Changes tab: local source control and remote pull-request
 * review in one surface. `useUIStore.gitWorkspaceView` picks the view, so
 * `openGitChanges` / `openGitReviews` land on the right one.
 */
export function GitWorkspacePanel({
  open,
  scope: reviewsScope,
  workspace,
  projectId,
  focus,
  onOpenInChat,
  onOpenWorkspace,
}: GitWorkspacePanelProps) {
  const view = useUIStore((state) => state.gitWorkspaceView)
  const setView = useUIStore((state) => state.setGitWorkspaceView)
  const scope: PullRequestsScope = view === 'reviews' ? reviewsScope : 'session'
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
        <div
          role="tablist"
          aria-label="Changes view"
          className="flex shrink-0 items-center gap-0.5 rounded-lg border border-(--color-border) bg-(--bg-key)/40 p-0.5"
        >
          {GIT_WORKSPACE_VIEWS.map((option) => (
            <button
              key={option.value}
              type="button"
              role="tab"
              aria-selected={view === option.value}
              onClick={() => setView(option.value)}
              className={cn(
                'focus-ring-control h-6 rounded-md px-2.5 text-[11px] font-medium transition-colors',
                view === option.value
                  ? 'bg-(--bg-card) text-(--color-text) shadow-[0_1px_2px_rgba(0,0,0,0.08)]'
                  : 'text-(--color-text-muted) hover:text-(--color-text)',
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
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
            <div className="flex h-full min-h-0 flex-col items-center justify-center gap-3 px-6 text-center">
              <GitBranch size={18} className="text-(--color-text-muted)" aria-hidden />
              <p className="text-sm font-medium text-(--color-text)">No workspace open</p>
              <p className="max-w-xs text-xs text-(--color-text-muted)">
                Open a coding workspace to review and commit local changes.
              </p>
              {onOpenWorkspace && (
                <button
                  type="button"
                  onClick={onOpenWorkspace}
                  className="focus-ring-control mt-1 rounded-lg border border-(--color-border) bg-(--bg-key) px-3 py-1.5 text-xs font-medium text-(--color-text) transition-colors hover:border-(--color-border-strong)"
                >
                  Open workspace
                </button>
              )}
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
