import { useState } from 'react'
import { CheckSquare, Square, GitCommit, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useToastStore } from '@/stores/useToastStore'
import {
  useGitChangesQuery,
  useGitCommitMutation,
  useGitStageMutation,
  useGitUnstageMutation,
  useGitLogQuery,
} from '@/queries/useGitQuery'
import { SourceControlFileList } from './SourceControlFileList'

export interface SourceControlCommitProps {
  workspace: string
}

export function SourceControlCommit({ workspace }: SourceControlCommitProps) {
  const [message, setMessage] = useState('')
  const [amend, setAmend] = useState(false)
  const changesQuery = useGitChangesQuery(workspace)
  const commitMutation = useGitCommitMutation(workspace)
  const stageMutation = useGitStageMutation(workspace)
  const unstageMutation = useGitUnstageMutation(workspace)
  const logQuery = useGitLogQuery(workspace, 0, undefined, amend)

  const files = changesQuery.data?.files ?? []
  const stagedFiles = files.filter((f) => f.staged)
  const unstagedFiles = files.filter((f) => !f.staged)

  const handleCommit = () => {
    if (!message.trim() && !amend) return
    commitMutation.mutate(
      { message: message.trim(), amend },
      {
        onSuccess: () => {
          setMessage('')
          setAmend(false)
          useToastStore.getState().push({ tone: 'success', title: 'Changes committed' })
        },
        onError: (err) => {
          useToastStore.getState().push({
            tone: 'error',
            title: 'Commit failed',
            description: err instanceof Error ? err.message : undefined,
          })
        },
      },
    )
  }

  const handleStageAll = () => {
    const paths = unstagedFiles.map((f) => f.path)
    if (paths.length > 0) {
      stageMutation.mutate(paths, {
        onSuccess: () => {
          useToastStore.getState().push({ tone: 'success', title: `Staged ${paths.length} file${paths.length > 1 ? 's' : ''}` })
        },
        onError: (err) => {
          useToastStore.getState().push({
            tone: 'error',
            title: 'Stage failed',
            description: err instanceof Error ? err.message : undefined,
          })
        },
      })
    }
  }

  const handleUnstageAll = () => {
    const paths = stagedFiles.map((f) => f.path)
    if (paths.length > 0) {
      unstageMutation.mutate(paths, {
        onSuccess: () => {
          useToastStore.getState().push({ tone: 'success', title: `Unstaged ${paths.length} file${paths.length > 1 ? 's' : ''}` })
        },
        onError: (err) => {
          useToastStore.getState().push({
            tone: 'error',
            title: 'Unstage failed',
            description: err instanceof Error ? err.message : undefined,
          })
        },
      })
    }
  }

  const handleAmendToggle = () => {
    const next = !amend
    setAmend(next)
    if (next && !message) {
      const latest = logQuery.data?.entries?.[0]
      if (latest) setMessage(latest.message)
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Message area */}
      <div className="shrink-0 border-b border-(--color-border) p-3">
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Commit message…"
          rows={3}
          className="w-full resize-none rounded-md border border-(--color-border) bg-(--bg-key) px-3 py-2 text-xs text-(--color-text) outline-none placeholder:text-(--color-text-subtle) focus:border-(--color-accent)"
        />
        <div className="mt-2 flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-[11px] text-(--color-text-muted)">
            <input
              type="checkbox"
              checked={amend}
              onChange={handleAmendToggle}
              className="h-3 w-3 accent-(--color-accent)"
            />
            Amend
          </label>
          <div className="flex-1" />
          <button
            type="button"
            onClick={handleCommit}
            disabled={commitMutation.isPending || (!message.trim() && !amend) || stagedFiles.length === 0}
            className={cn(
              'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
              'bg-(--color-accent) text-white hover:bg-(--color-accent)/90 disabled:opacity-50',
            )}
          >
            {commitMutation.isPending ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <GitCommit size={12} />
            )}
            Commit
          </button>
        </div>
      </div>

      {/* Staged files */}
      <div className="shrink-0 border-b border-(--color-border)">
        <div className="flex items-center justify-between px-3 py-1.5">
          <span className="text-[11px] font-medium uppercase tracking-wide text-(--color-text-subtle)">
            Staged ({stagedFiles.length})
          </span>
          <button
            type="button"
            onClick={handleUnstageAll}
            disabled={stagedFiles.length === 0}
            className="text-[11px] text-(--color-text-muted) hover:text-(--color-text) disabled:opacity-40"
            title="Unstage all"
          >
            <CheckSquare size={13} />
          </button>
        </div>
        <div className="max-h-40 overflow-auto px-1 pb-1">
          {changesQuery.isLoading ? (
            <p className="px-2 py-4 text-xs text-(--color-text-subtle)">Loading files…</p>
          ) : (
            <SourceControlFileList
              files={stagedFiles}
              onUnstage={(path) => unstageMutation.mutate([path])}
              showStageControls
              showDiscard={false}
            />
          )}
        </div>
      </div>

      {/* Unstaged files */}
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="flex items-center justify-between px-3 py-1.5">
          <span className="text-[11px] font-medium uppercase tracking-wide text-(--color-text-subtle)">
            Changes ({unstagedFiles.length})
          </span>
          <button
            type="button"
            onClick={handleStageAll}
            disabled={unstagedFiles.length === 0}
            className="text-[11px] text-(--color-text-muted) hover:text-(--color-text) disabled:opacity-40"
            title="Stage all"
          >
            <Square size={13} />
          </button>
        </div>
        <div className="px-1 pb-1">
          {changesQuery.isLoading ? (
            <p className="px-2 py-4 text-xs text-(--color-text-subtle)">Loading files…</p>
          ) : (
            <SourceControlFileList
              files={unstagedFiles}
              onStage={(path) => stageMutation.mutate([path])}
              showStageControls
              showDiscard={false}
            />
          )}
        </div>
      </div>
    </div>
  )
}
