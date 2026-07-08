import { useState } from 'react'
import { Archive, Plus, Play, ArrowUpFromLine, Trash2, Loader2 } from 'lucide-react'
import { useToastStore } from '@/stores/useToastStore'
import {
  useGitStashesQuery,
  useGitStashCreateMutation,
  useGitStashApplyMutation,
  useGitStashPopMutation,
  useGitStashDropMutation,
} from '@/queries/useGitQuery'

export interface SourceControlStashProps {
  workspace: string
}

export function SourceControlStash({ workspace }: SourceControlStashProps) {
  const [showCreate, setShowCreate] = useState(false)
  const [message, setMessage] = useState('')
  const [includeUntracked, setIncludeUntracked] = useState(false)
  const stashesQuery = useGitStashesQuery(workspace)
  const createMutation = useGitStashCreateMutation(workspace)
  const applyMutation = useGitStashApplyMutation(workspace)
  const popMutation = useGitStashPopMutation(workspace)
  const dropMutation = useGitStashDropMutation(workspace)

  const stashes = stashesQuery.data ?? []

  const busy = applyMutation.isPending || popMutation.isPending || dropMutation.isPending

  const handleCreate = () => {
    createMutation.mutate(
      { message: message.trim() || undefined, includeUntracked },
      {
        onSuccess: () => {
          setMessage('')
          setShowCreate(false)
          useToastStore.getState().push({ tone: 'success', title: 'Stash created' })
        },
        onError: (err) => {
          useToastStore.getState().push({
            tone: 'error',
            title: 'Stash failed',
            description: err instanceof Error ? err.message : undefined,
          })
        },
      },
    )
  }

  const handleApply = (index: number) => {
    applyMutation.mutate(index, {
      onSuccess: (data) => {
        if (data.success) {
          useToastStore.getState().push({ tone: 'success', title: 'Stash applied' })
        } else {
          useToastStore.getState().push({
            tone: 'error',
            title: 'Apply has conflicts',
            description: data.conflicts.join(', '),
          })
        }
      },
      onError: (err) => {
        useToastStore.getState().push({
          tone: 'error',
          title: 'Apply failed',
          description: err instanceof Error ? err.message : undefined,
        })
      },
    })
  }

  const handlePop = (index: number) => {
    popMutation.mutate(index, {
      onSuccess: (data) => {
        if (data.success) {
          useToastStore.getState().push({ tone: 'success', title: 'Stash popped' })
        } else {
          useToastStore.getState().push({
            tone: 'error',
            title: 'Pop has conflicts',
            description: data.conflicts.join(', '),
          })
        }
      },
      onError: (err) => {
        useToastStore.getState().push({
          tone: 'error',
          title: 'Pop failed',
          description: err instanceof Error ? err.message : undefined,
        })
      },
    })
  }

  const handleDrop = (index: number) => {
    dropMutation.mutate(index, {
      onSuccess: () => {
        useToastStore.getState().push({ tone: 'success', title: 'Stash dropped' })
      },
      onError: (err) => {
        useToastStore.getState().push({
          tone: 'error',
          title: 'Drop failed',
          description: err instanceof Error ? err.message : undefined,
        })
      },
    })
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-(--color-border) px-3 py-2">
        <span className="text-xs font-medium text-(--color-text-muted)">Stashes ({stashes.length})</span>
        <button
          type="button"
          onClick={() => setShowCreate((v) => !v)}
          className="rounded p-1 text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
          title="Create stash"
        >
          <Plus size={13} />
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="border-b border-(--color-border) p-3">
          <input
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleCreate()
              if (e.key === 'Escape') { setShowCreate(false); setMessage('') }
            }}
            placeholder="Stash message (optional)"
            className="w-full rounded border border-(--color-border) bg-(--bg-key) px-2 py-1.5 text-xs text-(--color-text) outline-none focus:border-(--color-accent)"
            autoFocus
          />
          <div className="mt-2 flex items-center justify-between">
            <label className="flex items-center gap-1.5 text-[11px] text-(--color-text-muted)">
              <input
                type="checkbox"
                checked={includeUntracked}
                onChange={(e) => setIncludeUntracked(e.target.checked)}
                className="h-3 w-3 accent-(--color-accent)"
              />
              Include untracked
            </label>
            <button
              type="button"
              onClick={handleCreate}
              disabled={createMutation.isPending}
              className="flex items-center gap-1 rounded bg-(--color-accent) px-2 py-1 text-[11px] font-medium text-white disabled:opacity-50"
            >
              {createMutation.isPending ? <Loader2 size={10} className="animate-spin" /> : <Archive size={10} />}
              Stash
            </button>
          </div>
        </div>
      )}

      {/* Stash list */}
      {stashesQuery.isLoading ? (
        <p className="px-3 py-4 text-xs text-(--color-text-subtle)">Loading stashes…</p>
      ) : stashesQuery.isError ? (
        <p className="px-3 py-4 text-xs text-(--color-error)">Failed to load stashes</p>
      ) : stashes.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <Archive size={24} className="mb-2 text-(--color-text-muted) opacity-40" />
          <p className="text-xs text-(--color-text-subtle)">No stashes</p>
        </div>
      ) : (
        <div className="divide-y divide-(--color-border)">
          {stashes.map((stash) => (
            <div
              key={stash.index}
              className="group flex items-center gap-2 px-3 py-2 hover:bg-(--bg-key)"
            >
              <Archive size={12} className="shrink-0 text-(--color-text-subtle)" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs text-(--color-text)">{stash.message}</p>
                <p className="font-mono text-[10px] text-(--color-text-subtle)">{stash.sha.slice(0, 8)}</p>
              </div>
              <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                <button
                  type="button"
                  onClick={() => handleApply(stash.index)}
                  disabled={busy}
                  aria-label="Apply stash"
                  className="rounded p-1 text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-50"
                  title="Apply"
                >
                  <Play size={11} />
                </button>
                <button
                  type="button"
                  onClick={() => handlePop(stash.index)}
                  disabled={busy}
                  aria-label="Pop stash"
                  className="rounded p-1 text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-50"
                  title="Pop"
                >
                  <ArrowUpFromLine size={11} />
                </button>
                <button
                  type="button"
                  onClick={() => handleDrop(stash.index)}
                  disabled={busy}
                  aria-label="Drop stash"
                  className="rounded p-1 text-(--color-text-muted) hover:bg-(--color-error)/10 hover:text-(--color-error) disabled:opacity-50"
                  title="Drop"
                >
                  <Trash2 size={11} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
