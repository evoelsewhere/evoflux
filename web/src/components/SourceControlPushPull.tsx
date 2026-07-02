import { Loader2, CloudDownload, CloudUpload, RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useToastStore } from '@/stores/useToastStore'
import {
  useGitChangesQuery,
  useGitFetchMutation,
  useGitPullMutation,
  useGitPushMutation,
  useGitJobsQuery,
} from '@/queries/useGitQuery'

export interface SourceControlPushPullProps {
  workspace: string
}

export function SourceControlPushPull({ workspace }: SourceControlPushPullProps) {
  const changesQuery = useGitChangesQuery(workspace)
  const jobsQuery = useGitJobsQuery(workspace)
  const fetchMutation = useGitFetchMutation(workspace)
  const pullMutation = useGitPullMutation(workspace)
  const pushMutation = useGitPushMutation(workspace)

  const { ahead, behind } = changesQuery.data ?? { ahead: 0, behind: 0 }
  const runningJob = jobsQuery.data?.status === 'running' ? jobsQuery.data : null

  const handleFetch = () => {
    fetchMutation.mutate(undefined, {
      onSuccess: (data) => {
        useToastStore.getState().push({
          tone: data.error ? 'error' : 'success',
          title: 'Fetch complete',
          description: data.message || data.error || undefined,
        })
      },
      onError: (err) => {
        useToastStore.getState().push({
          tone: 'error',
          title: 'Fetch failed',
          description: err instanceof Error ? err.message : undefined,
        })
      },
    })
  }

  const handlePull = () => {
    pullMutation.mutate(undefined, {
      onSuccess: (data) => {
        useToastStore.getState().push({
          tone: data.error ? 'error' : 'success',
          title: 'Pull complete',
          description: data.message || data.error || undefined,
        })
      },
      onError: (err) => {
        useToastStore.getState().push({
          tone: 'error',
          title: 'Pull failed',
          description: err instanceof Error ? err.message : undefined,
        })
      },
    })
  }

  const handlePush = () => {
    pushMutation.mutate(undefined, {
      onSuccess: (data) => {
        useToastStore.getState().push({
          tone: data.error ? 'error' : 'success',
          title: 'Push complete',
          description: data.message || data.error || undefined,
        })
      },
      onError: (err) => {
        useToastStore.getState().push({
          tone: 'error',
          title: 'Push failed',
          description: err instanceof Error ? err.message : undefined,
        })
      },
    })
  }

  const busy = fetchMutation.isPending || pullMutation.isPending || pushMutation.isPending

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Status bar */}
      <div className="flex items-center gap-4 border-b border-(--color-border) px-4 py-3">
        <div className="text-xs text-(--color-text-muted)">
          <span className="font-medium text-(--color-text)">{ahead}</span> ahead
        </div>
        <div className="text-xs text-(--color-text-muted)">
          <span className="font-medium text-(--color-text)">{behind}</span> behind
        </div>
        {runningJob && (
          <div className="flex items-center gap-1.5 text-xs text-(--color-text-muted)">
            <Loader2 size={12} className="animate-spin" />
            {runningJob.op}: {runningJob.message || 'running…'}
          </div>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex flex-col gap-2 p-4">
        <ActionButton
          icon={<CloudDownload size={14} />}
          label="Fetch"
          description="Download remote changes without merging"
          onClick={handleFetch}
          loading={fetchMutation.isPending}
          disabled={busy}
        />
        <ActionButton
          icon={<RefreshCw size={14} />}
          label="Pull"
          description={behind > 0 ? `${behind} commits behind — pull to update` : 'Fetch and merge remote changes'}
          onClick={handlePull}
          loading={pullMutation.isPending}
          disabled={busy}
          accent={behind > 0}
        />
        <ActionButton
          icon={<CloudUpload size={14} />}
          label="Push"
          description={ahead > 0 ? `${ahead} commits ahead — push to remote` : 'Upload local commits to remote'}
          onClick={handlePush}
          loading={pushMutation.isPending}
          disabled={busy}
          accent={ahead > 0}
        />
      </div>
    </div>
  )
}

function ActionButton({
  icon,
  label,
  description,
  onClick,
  loading,
  disabled,
  accent,
}: {
  icon: React.ReactNode
  label: string
  description: string
  onClick: () => void
  loading: boolean
  disabled: boolean
  accent?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'flex items-center gap-3 rounded-md border px-4 py-3 text-left transition-colors',
        accent
          ? 'border-(--color-accent)/30 bg-(--color-accent)/10 hover:bg-(--color-accent)/20'
          : 'border-(--color-border) hover:bg-(--bg-key)',
        disabled && 'opacity-60',
      )}
    >
      <div className={cn('shrink-0', accent ? 'text-(--color-accent)' : 'text-(--color-text-muted)')}>
        {loading ? <Loader2 size={14} className="animate-spin" /> : icon}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium text-(--color-text)">{label}</p>
        <p className="text-[11px] text-(--color-text-subtle)">{description}</p>
      </div>
    </button>
  )
}
