import { useState } from 'react'
import {
  GitBranch,
  Check,
  ChevronDown,
  ChevronRight,
  Plus,
  Trash2,
  ArrowRightLeft,
  GitMerge,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useToastStore } from '@/stores/useToastStore'
import {
  useGitBranchesQuery,
  useGitCheckoutMutation,
  useGitCreateBranchMutation,
  useGitDeleteBranchMutation,
  useGitMergeMutation,
  useGitRebaseMutation,
} from '@/queries/useGitQuery'

export interface SourceControlBranchesProps {
  workspace: string
}

export function SourceControlBranches({ workspace }: SourceControlBranchesProps) {
  const [newBranch, setNewBranch] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [selectedBranch, setSelectedBranch] = useState<string | null>(null)
  const branchesQuery = useGitBranchesQuery(workspace)
  const checkoutMutation = useGitCheckoutMutation(workspace)
  const createBranchMutation = useGitCreateBranchMutation(workspace)
  const deleteBranchMutation = useGitDeleteBranchMutation(workspace)
  const mergeMutation = useGitMergeMutation(workspace)
  const rebaseMutation = useGitRebaseMutation(workspace)

  const branches = branchesQuery.data ?? []
  const localBranches = branches.filter((b) => !b.remote)
  const remoteBranches = branches.filter((b) => b.remote)
  const currentBranch = branches.find((b) => b.current)

  const busy = checkoutMutation.isPending || createBranchMutation.isPending || deleteBranchMutation.isPending || mergeMutation.isPending || rebaseMutation.isPending

  if (branchesQuery.isLoading) {
    return (
      <div className="flex min-h-0 flex-1 flex-col overflow-auto">
        <div className="flex items-center justify-between border-b border-(--color-border) px-3 py-2">
          <span className="text-xs font-medium text-(--color-text-muted)">Branches</span>
        </div>
        <p className="px-3 py-4 text-xs text-(--color-text-subtle)">Loading branches…</p>
      </div>
    )
  }

  const handleCreate = () => {
    if (!newBranch.trim()) return
    createBranchMutation.mutate(newBranch.trim(), {
      onSuccess: () => {
        setNewBranch('')
        setShowCreate(false)
        useToastStore.getState().push({ tone: 'success', title: `Branch "${newBranch.trim()}" created` })
      },
      onError: (err) => {
        useToastStore.getState().push({
          tone: 'error',
          title: 'Failed to create branch',
          description: err instanceof Error ? err.message : undefined,
        })
      },
    })
  }

  const handleCheckout = (name: string) => {
    checkoutMutation.mutate(name, {
      onSuccess: () => {
        useToastStore.getState().push({ tone: 'success', title: `Switched to "${name}"` })
      },
      onError: (err) => {
        useToastStore.getState().push({
          tone: 'error',
          title: 'Checkout failed',
          description: err instanceof Error ? err.message : undefined,
        })
      },
    })
  }

  const handleDelete = (name: string) => {
    deleteBranchMutation.mutate({ name }, {
      onSuccess: () => {
        useToastStore.getState().push({ tone: 'success', title: `Branch "${name}" deleted` })
        if (selectedBranch === name) setSelectedBranch(null)
      },
      onError: (err) => {
        useToastStore.getState().push({
          tone: 'error',
          title: 'Delete failed',
          description: err instanceof Error ? err.message : undefined,
        })
      },
    })
  }

  const handleMerge = (branch: string) => {
    mergeMutation.mutate(branch, {
      onSuccess: (data) => {
        if (data.success) {
          useToastStore.getState().push({ tone: 'success', title: `Merged "${branch}"` })
        } else {
          useToastStore.getState().push({
            tone: 'error',
            title: 'Merge has conflicts',
            description: data.conflicts.join(', '),
          })
        }
      },
      onError: (err) => {
        useToastStore.getState().push({
          tone: 'error',
          title: 'Merge failed',
          description: err instanceof Error ? err.message : undefined,
        })
      },
    })
  }

  const handleRebase = (onto: string) => {
    rebaseMutation.mutate(onto, {
      onSuccess: (data) => {
        if (data.success) {
          useToastStore.getState().push({ tone: 'success', title: `Rebased onto "${onto}"` })
        } else {
          useToastStore.getState().push({
            tone: 'error',
            title: 'Rebase has conflicts',
            description: data.conflicts.join(', '),
          })
        }
      },
      onError: (err) => {
        useToastStore.getState().push({
          tone: 'error',
          title: 'Rebase failed',
          description: err instanceof Error ? err.message : undefined,
        })
      },
    })
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-(--color-border) px-3 py-2">
        <span className="text-xs font-medium text-(--color-text-muted)">Branches</span>
        <button
          type="button"
          onClick={() => setShowCreate((v) => !v)}
          className="rounded p-1 text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
          title="New branch"
        >
          <Plus size={13} />
        </button>
      </div>

      {/* Create branch form */}
      {showCreate && (
        <div className="flex items-center gap-1.5 border-b border-(--color-border) px-3 py-2">
          <input
            value={newBranch}
            onChange={(e) => setNewBranch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleCreate()
              if (e.key === 'Escape') { setShowCreate(false); setNewBranch('') }
            }}
            placeholder="branch-name"
            className="flex-1 rounded border border-(--color-border) bg-(--bg-key) px-2 py-1 text-xs text-(--color-text) outline-none focus:border-(--color-accent)"
            autoFocus
          />
          <button
            type="button"
            onClick={handleCreate}
            disabled={createBranchMutation.isPending || !newBranch.trim()}
            className="rounded bg-(--color-accent) px-2 py-1 text-[11px] font-medium text-white disabled:opacity-50"
          >
            Create
          </button>
        </div>
      )}

      {/* Local branches */}
      <BranchSection
        title="Local"
        branches={localBranches}
        selectedBranch={selectedBranch}
        onSelect={setSelectedBranch}
        onCheckout={handleCheckout}
        onDelete={handleDelete}
        onMerge={handleMerge}
        onRebase={handleRebase}
        busy={busy}
      />

      {/* Remote branches */}
      {remoteBranches.length > 0 && (
        <BranchSection
          title="Remote"
          branches={remoteBranches}
          selectedBranch={selectedBranch}
          onSelect={setSelectedBranch}
          onCheckout={handleCheckout}
          onDelete={handleDelete}
          onMerge={handleMerge}
          onRebase={handleRebase}
          busy={busy}
        />
      )}
    </div>
  )
}

function BranchSection({
  title,
  branches,
  selectedBranch,
  onSelect,
  onCheckout,
  onDelete,
  onMerge,
  onRebase,
  busy,
}: {
  title: string
  branches: Array<{ name: string; current: boolean; remote: string | null; ahead: number; behind: number }>
  selectedBranch: string | null
  onSelect: (name: string | null) => void
  onCheckout: (name: string) => void
  onDelete: (name: string) => void
  onMerge: (branch: string) => void
  onRebase: (onto: string) => void
  busy?: boolean
}) {
  const [expanded, setExpanded] = useState(true)

  return (
    <div className="border-b border-(--color-border)">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left"
      >
        {expanded ? (
          <ChevronDown size={11} className="shrink-0 text-(--color-text-subtle)" />
        ) : (
          <ChevronRight size={11} className="shrink-0 text-(--color-text-subtle)" />
        )}
        <span className="text-[11px] font-medium uppercase tracking-wide text-(--color-text-subtle)">
          {title}
        </span>
        <span className="text-[10px] text-(--color-text-subtle)">({branches.length})</span>
      </button>
      {expanded && (
        <div className="space-y-0.5 pb-1">
          {branches.map((branch) => {
            const isSelected = selectedBranch === branch.name
            return (
              <div key={branch.name}>
                <button
                  type="button"
                  onClick={() => onSelect(isSelected ? null : branch.name)}
                  className={cn(
                    'flex w-full items-center gap-1.5 rounded px-3 py-1 text-left text-xs transition-colors',
                    isSelected ? 'bg-(--bg-key) text-(--color-text)' : 'hover:bg-(--bg-key)',
                  )}
                >
                  <GitBranch size={11} className="shrink-0 text-(--color-text-subtle)" />
                  <span className="min-w-0 flex-1 truncate font-mono text-(--color-text)">
                    {branch.name}
                  </span>
                  {branch.current && (
                    <Check size={12} className="shrink-0 text-green-400" />
                  )}
                  {branch.ahead > 0 && (
                    <span className="shrink-0 text-[10px] text-green-400">↑{branch.ahead}</span>
                  )}
                  {branch.behind > 0 && (
                    <span className="shrink-0 text-[10px] text-amber-400">↓{branch.behind}</span>
                  )}
                </button>
                {isSelected && !branch.current && (
                  <div className="flex items-center gap-1 px-5 py-1">
                    <button
                      type="button"
                      onClick={() => onCheckout(branch.name)}
                      disabled={busy}
                      aria-label={`Checkout branch ${branch.name}`}
                      className="flex items-center gap-1 rounded px-2 py-0.5 text-[11px] text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-50"
                    >
                      <ArrowRightLeft size={10} /> Checkout
                    </button>
                    <button
                      type="button"
                      onClick={() => onMerge(branch.name)}
                      disabled={busy}
                      aria-label={`Merge branch ${branch.name}`}
                      className="flex items-center gap-1 rounded px-2 py-0.5 text-[11px] text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-50"
                    >
                      <GitMerge size={10} /> Merge
                    </button>
                    <button
                      type="button"
                      onClick={() => onRebase(branch.name)}
                      disabled={busy}
                      aria-label={`Rebase onto ${branch.name}`}
                      className="flex items-center gap-1 rounded px-2 py-0.5 text-[11px] text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-50"
                    >
                      Rebase
                    </button>
                    <button
                      type="button"
                      onClick={() => onDelete(branch.name)}
                      disabled={busy}
                      aria-label={`Delete branch ${branch.name}`}
                      className="flex items-center gap-1 rounded px-2 py-0.5 text-[11px] text-(--color-text-muted) hover:bg-(--color-error)/10 hover:text-(--color-error) disabled:opacity-50"
                    >
                      <Trash2 size={10} /> Delete
                    </button>
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
