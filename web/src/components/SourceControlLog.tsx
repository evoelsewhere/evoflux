import { useState } from 'react'
import { ChevronDown, ChevronRight, Cherry } from 'lucide-react'
import { useToastStore } from '@/stores/useToastStore'
import { useGitLogQuery, useGitLogFilesQuery, useGitCherryPickMutation } from '@/queries/useGitQuery'

export interface SourceControlLogProps {
  workspace: string
}

export function SourceControlLog({ workspace }: SourceControlLogProps) {
  const [page, setPage] = useState(0)
  const [expandedSha, setExpandedSha] = useState<string | null>(null)
  const logQuery = useGitLogQuery(workspace, page)
  const logFilesQuery = useGitLogFilesQuery(workspace, expandedSha, !!expandedSha)
  const cherryPickMutation = useGitCherryPickMutation(workspace)

  const entries = logQuery.data?.entries ?? []
  const hasMore = logQuery.data?.has_more ?? false

  const handleCherryPick = (sha: string) => {
    cherryPickMutation.mutate([sha], {
      onSuccess: (data) => {
        if (data.success) {
          useToastStore.getState().push({ tone: 'success', title: 'Cherry-pick applied' })
        } else {
          useToastStore.getState().push({
            tone: 'error',
            title: 'Cherry-pick has conflicts',
            description: data.conflicts.join(', '),
          })
        }
      },
      onError: (err) => {
        useToastStore.getState().push({
          tone: 'error',
          title: 'Cherry-pick failed',
          description: err instanceof Error ? err.message : undefined,
        })
      },
    })
  }

  const copySha = (sha: string) => {
    void navigator.clipboard.writeText(sha)
    useToastStore.getState().push({ tone: 'info', title: 'SHA copied' })
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto">
      <div className="flex items-center justify-between border-b border-(--color-border) px-3 py-2">
        <span className="text-xs font-medium text-(--color-text-muted)">Commit log</span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="rounded px-2 py-0.5 text-[11px] text-(--color-text-muted) hover:bg-(--bg-key) disabled:opacity-40"
          >
            Newer
          </button>
          <span className="text-[11px] text-(--color-text-subtle)">p{page + 1}</span>
          <button
            type="button"
            onClick={() => setPage((p) => p + 1)}
            disabled={!hasMore}
            className="rounded px-2 py-0.5 text-[11px] text-(--color-text-muted) hover:bg-(--bg-key) disabled:opacity-40"
          >
            Older
          </button>
        </div>
      </div>

      {logQuery.isLoading ? (
        <p className="px-3 py-4 text-xs text-(--color-text-subtle)">Loading log…</p>
      ) : logQuery.isError ? (
        <p className="px-3 py-4 text-xs text-(--color-error)">Failed to load log</p>
      ) : entries.length === 0 ? (
        <p className="px-3 py-4 text-xs text-(--color-text-subtle)">No commits</p>
      ) : (
        <div className="divide-y divide-(--color-border)">
          {entries.map((entry) => {
            const isExpanded = expandedSha === entry.sha
            return (
              <div key={entry.sha}>
                <button
                  type="button"
                  onClick={() => setExpandedSha(isExpanded ? null : entry.sha)}
                  className="flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-(--bg-key)"
                >
                  {isExpanded ? (
                    <ChevronDown size={12} className="mt-0.5 shrink-0 text-(--color-text-subtle)" />
                  ) : (
                    <ChevronRight size={12} className="mt-0.5 shrink-0 text-(--color-text-subtle)" />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs text-(--color-text)">{entry.message}</p>
                    <p className="mt-0.5 flex items-center gap-2 text-[10px] text-(--color-text-subtle)">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          copySha(entry.sha)
                        }}
                        className="font-mono hover:text-(--color-text)"
                        title="Copy full SHA"
                      >
                        {entry.short_sha}
                      </button>
                      <span>{entry.author}</span>
                      <span>{formatDate(entry.date)}</span>
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleCherryPick(entry.sha)
                    }}
                    className="shrink-0 rounded p-1 text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
                    title="Cherry-pick this commit"
                  >
                    <Cherry size={12} />
                  </button>
                </button>
                {isExpanded && (
                  <div className="border-t border-(--color-border) bg-(--bg-key)/50 px-6 py-2">
                    {logFilesQuery.isLoading ? (
                      <p className="text-[11px] text-(--color-text-subtle)">Loading files…</p>
                    ) : logFilesQuery.isError ? (
                      <p className="text-[11px] text-(--color-error)">Failed to load files</p>
                    ) : (logFilesQuery.data ?? []).length === 0 ? (
                      <p className="text-[11px] text-(--color-text-subtle)">No file changes</p>
                    ) : (
                      <div className="space-y-0.5">
                        {(logFilesQuery.data ?? []).map((f) => (
                          <div key={f.path} className="flex items-center gap-2 text-[11px]">
                            <span className="w-4 shrink-0 text-center font-mono text-(--color-text-muted)">
                              {f.status}
                            </span>
                            <span className="truncate font-mono text-(--color-text)">{f.path}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso)
    const now = new Date()
    const diffMs = now.getTime() - d.getTime()
    const diffMins = Math.floor(diffMs / 60_000)
    if (diffMins < 1) return 'just now'
    if (diffMins < 60) return `${diffMins}m ago`
    const diffHours = Math.floor(diffMins / 60)
    if (diffHours < 24) return `${diffHours}h ago`
    const diffDays = Math.floor(diffHours / 24)
    if (diffDays < 7) return `${diffDays}d ago`
    return d.toLocaleDateString()
  } catch {
    return iso
  }
}
