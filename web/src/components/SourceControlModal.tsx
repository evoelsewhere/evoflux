/** Local Git workspace with first-class changes, branches, history, and stash views. */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  GitBranch,
  GitCommit,
  History,
  Archive,
  X,
  CloudDownload,
  CloudUpload,
  RefreshCw,
  Loader2,
  Plus,
  Check,
  Trash2,
  ArrowRightLeft,
  GitMerge,
  Play,
  ArrowUpFromLine,
  Search,
  RotateCcw,
  PanelRightOpen,
  PanelRightClose,
  Copy,
  FileDiff,
  KeyRound,
  RadioTower,
  Tag,
  Pencil,
  UserRound,
  Sparkles,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Combobox } from '@/components/ui/combobox'
import { SelectControl } from '@/components/ui/select'
import { GitActionSurface, type GitAction } from '@/components/git/GitActionMenu'
import { useToastStore } from '@/stores/useToastStore'
import { queryKeys } from '@/queries'
import {
  useGitChangesQuery,
  useGitConflictsQuery,
  useGitContinueMutation,
  useGitAbortMutation,
  useGitBranchesQuery,
  useGitCheckoutMutation,
  useGitCreateBranchMutation,
  useGitDeleteBranchMutation,
  useGitMergeMutation,
  useGitRebaseMutation,
  useGitFetchMutation,
  useGitPullMutation,
  useGitPushMutation,
  useGitJobsQuery,
  useGitLogQuery,
  useGitLogFilesQuery,
  useGitCherryPickMutation,
  useGitStashesQuery,
  useGitStashCreateMutation,
  useGitStashApplyMutation,
  useGitStashPopMutation,
  useGitStashDropMutation,
  useGitStageMutation,
  useGitUnstageMutation,
  useGitDiscardMutation,
  useGitCommitMutation,
  useGitDiffViewQuery,
  useGitRepositoryQuery,
  useGitInitMutation,
  useGitRemotesQuery,
  useGitCreateRemoteMutation,
  useGitUpdateRemoteMutation,
  useGitDeleteRemoteMutation,
  useGitTagsQuery,
  useGitCreateTagMutation,
  useGitDeleteTagMutation,
  useGitPushTagsMutation,
  useGitSetIdentityMutation,
  useGitRevertMutation,
} from '@/queries/useGitQuery'
import type { CodingProject, ChangedFile, GitAIAction, GitAIResponse, GitLogEntry } from '@/api/types'
import { runGitAIAction } from '@/api/client'
import { useTeamStore } from '@/stores/useTeamStore'
import { useUIStore } from '@/stores/useUIStore'
import { useChangeSetStore } from '@/stores/useChangeSetStore'
import { GitAiResultDialog } from '@/components/GitAiResultDialog'
import { getIntlLocale } from '@/i18n'
import {
  parseUnifiedDiff,
  type UnifiedDiffHunk as DiffHunk,
  type UnifiedDiffLine as DiffLine,
} from '@/lib/unified-diff'

/* ── Helpers ─────────────────────────────────────────────────────────────── */

function repoLabel(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

function fileName(path: string): string {
  return path.split('/').pop() || path
}

function parentPath(path: string): string {
  const segments = path.split('/')
  return segments.length > 1 ? segments.slice(0, -1).join('/') : ''
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
    return d.toLocaleDateString(getIntlLocale())
  } catch {
    return iso
  }
}

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  modified: { label: 'M', cls: 'bg-amber-500/20 text-amber-400' },
  added: { label: 'A', cls: 'bg-green-500/20 text-green-400' },
  deleted: { label: 'D', cls: 'bg-red-500/20 text-red-400' },
  renamed: { label: 'R', cls: 'bg-blue-500/20 text-blue-400' },
  untracked: { label: '??', cls: 'bg-(--bg-key) text-(--color-text-muted)' },
  unmerged: { label: 'U', cls: 'bg-red-500/20 text-red-400' },
}

/* ── Types ───────────────────────────────────────────────────────────────── */

export interface SourceControlPanelProps {
  open: boolean
  workspace: string
  onWorkspaceChange?: (path: string) => void
  project?: CodingProject | null
  onFileOpenInEditor?: (path: string) => void
  credentialLabel?: string | null
}

/* ── Main panel ──────────────────────────────────────────────────────────── */

export function SourceControlPanel({
  open,
  workspace,
  onWorkspaceChange,
  project,
  credentialLabel,
}: SourceControlPanelProps) {
  const queryClient = useQueryClient()
  const observedRunningJob = useRef(false)
  const [showDiff, setShowDiff] = useState(true)
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [gitAiBusy, setGitAiBusy] = useState(false)
  const sessionId = useTeamStore((state) => state.sessionId)
  const openWorkbenchTool = useUIStore((state) => state.openWorkbenchTool)
  const setChangeSet = useChangeSetStore((state) => state.setActive)

  const [activeView, setActiveView] = useState<'changes' | 'branches' | 'history' | 'stash' | 'remotes' | 'tags'>('changes')

  // Core queries
  const repositoryQuery = useGitRepositoryQuery(workspace, open)
  const changesQuery = useGitChangesQuery(workspace, open)
  const conflictsQuery = useGitConflictsQuery(workspace, open)
  const branchesQuery = useGitBranchesQuery(workspace, open)
  const stashesQuery = useGitStashesQuery(workspace, open)
  const remotesQuery = useGitRemotesQuery(workspace, open)
  const tagsQuery = useGitTagsQuery(workspace, open)
  const jobsQuery = useGitJobsQuery(workspace, open)

  const branch = changesQuery.data?.branch
  const isGitRepo = changesQuery.data?.is_git_repo !== false
  const ahead = changesQuery.data?.ahead ?? 0
  const behind = changesQuery.data?.behind ?? 0
  const files = useMemo(() => changesQuery.data?.files ?? [], [changesQuery.data?.files])
  const stagedFiles = files.filter((f) => f.staged)
  const unstagedFiles = files.filter((f) => !f.staged)
  const localBranches = (branchesQuery.data ?? []).filter((b) => !b.remote)
  const stashes = stashesQuery.data ?? []
  const remotes = useMemo(() => remotesQuery.data ?? [], [remotesQuery.data])
  const tags = tagsQuery.data ?? []
  const repository = repositoryQuery.data
  const runningJob = jobsQuery.data?.status === 'running' ? jobsQuery.data : null
  const finishedJob = jobsQuery.data?.status !== 'running' ? jobsQuery.data : null
  const projectWorkspaces = project?.workspaces ?? []

  // Conflict handling
  const conflicts = conflictsQuery.data
  const hasConflicts = conflicts?.conflicted ?? false
  const continueMutation = useGitContinueMutation(workspace)
  const abortMutation = useGitAbortMutation(workspace)

  // Fetch / Push / Pull
  const fetchMutation = useGitFetchMutation(workspace)
  const pushMutation = useGitPushMutation(workspace)
  const pullMutation = useGitPullMutation(workspace)

  useEffect(() => {
    const job = jobsQuery.data
    if (!job) return
    if (job.status === 'running') {
      observedRunningJob.current = true
      return
    }
    if (!observedRunningJob.current) return
    observedRunningJob.current = false
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.git.changes(workspace) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.git.branches(workspace) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.git.log(workspace, 0) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.git.conflicts(workspace) }),
    ])
    if (job.status === 'done') {
      useToastStore.getState().push({
        tone: 'success',
        title: `${job.op.charAt(0).toUpperCase()}${job.op.slice(1)} complete`,
      })
    }
  }, [jobsQuery.data, queryClient, workspace])

  // Auto-select first file when dialog opens
  useEffect(() => {
    if (open && !selectedPath && files.length > 0) {
      setSelectedPath(files[0].path)
    }
  }, [open, files, selectedPath])

  const runAi = useCallback(async (action: GitAIAction, reference?: string) => {
    if (gitAiBusy) return
    if (!sessionId) {
      useToastStore.getState().push({
        tone: 'info',
        title: 'Open a coding task to use AI Git actions',
        description: 'The active task supplies the model and workspace authorization.',
      })
      return
    }
    setGitAiBusy(true)
    try {
      const result = await runGitAIAction(workspace, {
        session_id: sessionId,
        action,
        reference,
      })
      if (result.change_set) {
        setChangeSet(result.change_set)
      } else if (result.kind === 'review') {
        openWorkbenchTool('problems')
        useToastStore.getState().push({
          tone: 'info',
          title: result.findings.length
            ? `${result.findings.length} AI review finding${result.findings.length === 1 ? '' : 's'}`
            : 'AI review found no concrete problems',
        })
      }
    } catch (error) {
      useToastStore.getState().push({
        tone: 'error',
        title: 'AI Git action failed',
        description: error instanceof Error ? error.message : undefined,
      })
    } finally {
      setGitAiBusy(false)
    }
  }, [gitAiBusy, openWorkbenchTool, sessionId, setChangeSet, workspace])

  const reviewChanges = useCallback(() => {
    if (files.length === 0) {
      useToastStore.getState().push({
        tone: 'info',
        title: 'No changes to review',
      })
      return
    }
    void runAi('self_review')
  }, [files.length, runAi])

  useEffect(() => {
    if (!open) return
    const review = () => reviewChanges()
    window.addEventListener('evoflux:git-ai-review', review)
    return () => window.removeEventListener('evoflux:git-ai-review', review)
  }, [open, reviewChanges])

  return (
      <div
        aria-labelledby="sc-title"
        className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-(--bg-page)"
      >
        {/* Repository status and remote actions */}
        <div className="flex min-h-11 shrink-0 items-center gap-2 overflow-x-auto border-b border-(--color-border) px-3 py-1.5">
          <h2 id="sc-title" className="sr-only">Source Control repository actions</h2>
          {projectWorkspaces.length > 1 ? (
            <Combobox
              value={workspace}
              onValueChange={(value) => {
                if (value) onWorkspaceChange?.(value)
              }}
              items={projectWorkspaces.map((item) => ({
                value: item.path,
                label: item.display_name || item.name || repoLabel(item.path),
                description: item.path,
              }))}
              size="sm"
              clearable={false}
              ariaLabel="Repository"
              searchPlaceholder="Search repositories…"
              className="max-w-48 shrink-0 bg-(--bg-card) text-[11px]"
            />
          ) : null}
          {branch && (
            <span
              className="flex max-w-44 shrink-0 items-center gap-1.5 rounded-md bg-(--bg-key) px-2 py-1 text-[11px] font-medium text-(--color-text-muted)"
              title={repository?.upstream ? `${branch} tracks ${repository.upstream}` : branch}
            >
              <GitBranch size={12} />
              <span className="truncate">{branch}</span>
              {repository?.upstream && (
                <span className="truncate text-[9px] text-(--color-text-subtle)">→ {repository.upstream}</span>
              )}
            </span>
          )}
          {(ahead > 0 || behind > 0) && (
            <span className="flex shrink-0 items-center gap-1.5 text-[10px] font-medium">
              {ahead > 0 && <span className="text-(--color-success)">↑ {ahead}</span>}
              {behind > 0 && <span className="text-(--color-warning)">↓ {behind}</span>}
            </span>
          )}
          {runningJob && (
            <span className="flex shrink-0 items-center gap-1 text-[11px] text-(--color-text-muted)">
              <Loader2 size={10} className="animate-spin" /> {runningJob.op}…
            </span>
          )}
          {credentialLabel && (
            <span
              className="flex shrink-0 items-center gap-1 rounded-full bg-(--color-success-subtle) px-2 py-1 text-[10px] font-medium text-(--color-success)"
              title={`${credentialLabel} will be reused for HTTPS fetch, pull, and push`}
              aria-label="Saved Git credential ready"
            >
              <KeyRound size={10} />
              Auth
            </span>
          )}
          {repository?.is_git_repo && (!repository.user_name || !repository.user_email) && (
            <span
              className="flex shrink-0 items-center gap-1 rounded-full bg-(--color-warning-subtle) px-2 py-1 text-[10px] font-medium text-(--color-warning)"
              title="Configure git user.name and user.email before committing"
            >
              <UserRound size={10} />
              Identity
            </span>
          )}
          <div className="flex-1" />
          <ToolbarButton icon={<RefreshCw size={12} />} label="Refresh" onClick={() => changesQuery.refetch()} compact />
          <ToolbarButton
            icon={<CloudDownload size={12} />}
            label="Fetch"
            disabled={Boolean(runningJob) || !isGitRepo}
            onClick={() => fetchMutation.mutate(undefined, {
              onSuccess: () => {
                observedRunningJob.current = true
                useToastStore.getState().push({ tone: 'info', title: 'Fetch started' })
              },
              onError: (error) => useToastStore.getState().push({ tone: 'error', title: 'Fetch failed', description: error instanceof Error ? error.message : undefined }),
            })}
          />
          <ToolbarButton
            icon={<RefreshCw size={12} />}
            label="Pull"
            disabled={Boolean(runningJob) || !isGitRepo}
            onClick={() => pullMutation.mutate(undefined, {
              onSuccess: () => {
                observedRunningJob.current = true
                useToastStore.getState().push({ tone: 'info', title: 'Pull started' })
              },
              onError: (error) => useToastStore.getState().push({ tone: 'error', title: 'Pull failed', description: error instanceof Error ? error.message : undefined }),
            })}
            badge={behind > 0 ? String(behind) : undefined}
          />
          <ToolbarButton
            icon={<CloudUpload size={12} />}
            label="Push"
            disabled={Boolean(runningJob) || !isGitRepo}
            onClick={() => pushMutation.mutate(undefined, {
              onSuccess: () => {
                observedRunningJob.current = true
                useToastStore.getState().push({ tone: 'info', title: 'Push started' })
              },
              onError: (error) => useToastStore.getState().push({ tone: 'error', title: 'Push failed', description: error instanceof Error ? error.message : undefined }),
            })}
            badge={ahead > 0 ? String(ahead) : undefined}
          />
        </div>

        {/* Primary local Git view selector. This is deliberately a selector,
            not another tab strip inside the Workbench Changes tab. */}
        {isGitRepo && (
          <div className="flex h-10 shrink-0 items-center gap-2 border-b border-(--color-border) bg-(--bg-key)/20 px-2">
            <label htmlFor="source-control-view" className="text-[10px] font-medium text-(--color-text-muted)">
              View
            </label>
            <SelectControl
              id="source-control-view"
              value={activeView}
              onValueChange={(value) => setActiveView(value as typeof activeView)}
              size="sm"
              ariaLabel="Source control view"
              className="min-w-36 bg-(--bg-card) text-[11px] font-medium"
              options={[
                { value: 'changes', label: `Changes (${files.length})` },
                { value: 'branches', label: `Branches (${localBranches.length})` },
                { value: 'history', label: 'History' },
                { value: 'stash', label: `Stashes (${stashes.length})` },
                { value: 'remotes', label: `Remotes (${remotes.length})` },
                { value: 'tags', label: `Tags (${tags.length})` },
              ]}
            />
            <div className="min-w-0 flex-1" />
            {activeView === 'changes' && (
              <>
                <button
                  type="button"
                  onClick={reviewChanges}
                  disabled={gitAiBusy || files.length === 0}
                  className="flex h-7 shrink-0 items-center gap-1.5 rounded-md border border-(--color-border) bg-(--bg-card) px-2 text-[10px] font-medium text-(--color-accent) transition-colors hover:bg-(--bg-key) disabled:opacity-40"
                  title={
                    files.length === 0
                      ? 'No changes to review'
                      : sessionId
                        ? 'Review uncommitted changes and publish findings to Problems'
                        : 'Open a coding task to review changes with AI'
                  }
                >
                  {gitAiBusy
                    ? <Loader2 size={12} className="animate-spin" />
                    : <Sparkles size={12} />}
                  Review changes
                </button>
                <button
                  type="button"
                  onClick={() => setShowDiff(!showDiff)}
                  className={cn(
                    'flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[10px] font-medium transition-colors',
                    showDiff
                      ? 'bg-(--bg-key) text-(--color-text)'
                      : 'text-(--color-text-muted) hover:bg-(--bg-key)',
                  )}
                  title={showDiff ? 'Hide diff' : 'Show diff'}
                  aria-label={showDiff ? 'Hide diff' : 'Show diff'}
                >
                  {showDiff ? <PanelRightClose size={12} /> : <PanelRightOpen size={12} />}
                </button>
              </>
            )}
          </div>
        )}

        {finishedJob?.status === 'error' && (
          <div className="flex shrink-0 items-start gap-2 border-b border-(--color-error)/35 bg-(--color-error-subtle) px-3 py-2 text-[11px] text-(--color-error)">
            <X size={13} className="mt-px shrink-0" />
            <span className="min-w-0">
              <strong className="font-semibold capitalize">{finishedJob.op} failed.</strong>{' '}
              {finishedJob.error || 'Check the remote, branch, and credential configuration.'}
            </span>
          </div>
        )}

        {/* ═══ Conflict Banner ═════════════════════════════════════════════ */}
        {hasConflicts && (
          <ConflictBar
            conflicts={conflicts!}
            onContinue={() => continueMutation.mutate(undefined, { onSuccess: () => useToastStore.getState().push({ tone: 'success', title: 'Continued' }), onError: () => useToastStore.getState().push({ tone: 'error', title: 'Failed' }) })}
            onAbort={() => abortMutation.mutate(undefined, { onSuccess: () => useToastStore.getState().push({ tone: 'info', title: 'Aborted' }), onError: () => useToastStore.getState().push({ tone: 'error', title: 'Failed' }) })}
            onResolve={() => { void runAi('propose_conflict_resolution') }}
            resolving={gitAiBusy}
          />
        )}

        {/* Active Git view */}
        {!isGitRepo ? (
          <GitInitPanel workspace={workspace} />
        ) : (
        <div className="flex min-h-0 flex-1 overflow-hidden">
          {activeView === 'changes' && (
            <>
            <FileListPanel
              workspace={workspace}
              stagedFiles={stagedFiles}
              unstagedFiles={unstagedFiles}
              isLoading={changesQuery.isLoading}
              selectedPath={selectedPath}
              onSelect={setSelectedPath}
            />
            {showDiff && <DiffPanel workspace={workspace} path={selectedPath} />}
            </>
          )}
          {activeView === 'branches' && <BranchesPanel workspace={workspace} />}
          {activeView === 'history' && <HistoryPanel workspace={workspace} />}
          {activeView === 'stash' && <StashPanel workspace={workspace} />}
          {activeView === 'remotes' && (
            <RemotesPanel
              workspace={workspace}
              branch={repository?.branch ?? branch}
              upstream={repository?.upstream ?? null}
              userName={repository?.user_name ?? null}
              userEmail={repository?.user_email ?? null}
            />
          )}
          {activeView === 'tags' && <TagsPanel workspace={workspace} />}
        </div>
        )}

        {isGitRepo && activeView === 'changes' && <CommitArea workspace={workspace} stagedCount={stagedFiles.length} />}
      </div>
  )
}

/* ── Toolbar Button ──────────────────────────────────────────────────────── */

function ToolbarButton({ icon, label, onClick, badge, compact = false, disabled = false }: { icon: React.ReactNode; label: string; onClick: () => void; badge?: string; compact?: boolean; disabled?: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} title={label} aria-label={label} className="relative flex h-7 shrink-0 items-center gap-1.5 rounded-md border border-(--color-border) bg-(--bg-card) px-2 text-[10px] font-medium text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text) disabled:pointer-events-none disabled:opacity-40">
      {icon}
      {!compact && label}
      {badge && <span className="absolute -right-1 -top-1 flex h-3.5 min-w-[14px] items-center justify-center rounded-full bg-(--color-accent) px-0.5 text-[8px] font-bold text-(--color-text-on-accent)">{badge}</span>}
    </button>
  )
}

/* ── Conflict Banner ─────────────────────────────────────────────────────── */

function ConflictBar({ conflicts, onContinue, onAbort, onResolve, resolving }: {
  conflicts: { operation: string | null; files: { path: string; status: string }[] }
  onContinue: () => void
  onAbort: () => void
  onResolve: () => void
  resolving: boolean
}) {
  return (
    <div className="flex items-center gap-3 border-b border-red-500/35 bg-red-500/10 px-3 py-1.5">
      <span className="text-[11px] font-medium text-red-300">
        {conflicts.operation ? `${conflicts.operation} conflict` : 'Conflicts'} — {conflicts.files.length} file{conflicts.files.length !== 1 ? 's' : ''}
      </span>
      <div className="flex-1" />
      <button
        type="button"
        onClick={onResolve}
        disabled={resolving}
        className="flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium text-(--color-accent) hover:bg-(--bg-key) disabled:opacity-40"
      >
        {resolving
          ? <Loader2 size={11} className="animate-spin" />
          : <Sparkles size={11} />}
        Resolve with AI
      </button>
      <button type="button" onClick={onContinue} className="rounded bg-green-600 px-2 py-0.5 text-[11px] font-medium text-white hover:bg-green-500">Continue</button>
      <button type="button" onClick={onAbort} className="rounded px-2 py-0.5 text-[11px] text-red-300 hover:bg-red-500/20">Abort</button>
    </div>
  )
}

function GitInitPanel({ workspace }: { workspace: string }) {
  const [defaultBranch, setDefaultBranch] = useState('main')
  const initMutation = useGitInitMutation(workspace)

  return (
    <div className="flex min-h-0 flex-1 items-center justify-center p-6">
      <div className="w-full max-w-sm rounded-xl border border-(--color-border) bg-(--bg-card) p-5 shadow-sm">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-(--color-accent)/10 text-(--color-accent)">
          <GitBranch size={18} />
        </span>
        <h3 className="mt-4 text-sm font-semibold text-(--color-text)">Initialize repository</h3>
        <p className="mt-1 text-xs leading-5 text-(--color-text-muted)">
          Start tracking this workspace with Git. Existing files will not be committed automatically.
        </p>
        <label className="mt-4 block text-[10px] font-medium uppercase tracking-wider text-(--color-text-subtle)">
          Default branch
        </label>
        <div className="mt-1.5 flex gap-2">
          <input
            value={defaultBranch}
            onChange={(event) => setDefaultBranch(event.target.value)}
            className="h-8 min-w-0 flex-1 rounded-md border border-(--color-border) bg-(--bg-base) px-2.5 font-mono text-xs text-(--color-text) outline-none focus:border-(--color-accent)"
          />
          <button
            type="button"
            disabled={!defaultBranch.trim() || initMutation.isPending}
            onClick={() => initMutation.mutate(defaultBranch.trim(), {
              onSuccess: () => useToastStore.getState().push({ tone: 'success', title: 'Git repository initialized' }),
              onError: (error) => useToastStore.getState().push({ tone: 'error', title: 'Initialization failed', description: error instanceof Error ? error.message : undefined }),
            })}
            className="flex h-8 items-center gap-1.5 rounded-md bg-(--color-accent) px-3 text-[11px] font-semibold text-(--color-text-on-accent) disabled:opacity-40"
          >
            {initMutation.isPending && <Loader2 size={11} className="animate-spin" />}
            Initialize
          </button>
        </div>
      </div>
    </div>
  )
}

/* ── Commit composer ────────────────────────────────────────────────────── */

function CommitArea({ workspace, stagedCount }: { workspace: string; stagedCount: number }) {
  const [message, setMessage] = useState('')
  const [amend, setAmend] = useState(false)
  const commitMutation = useGitCommitMutation(workspace)
  const sessionId = useTeamStore((state) => state.sessionId)
  const [generating, setGenerating] = useState(false)

  const handleCommit = useCallback(() => {
    if (!message.trim() && !amend) return
    commitMutation.mutate(
      { message: message.trim(), amend },
      {
        onSuccess: () => { setMessage(''); setAmend(false); useToastStore.getState().push({ tone: 'success', title: 'Committed' }) },
        onError: (err) => useToastStore.getState().push({ tone: 'error', title: 'Commit failed', description: err instanceof Error ? err.message : undefined }),
      },
    )
  }, [message, amend, commitMutation])

  const generateMessage = async () => {
    if (!sessionId || generating || stagedCount === 0) return
    setGenerating(true)
    try {
      const result = await runGitAIAction(workspace, {
        session_id: sessionId,
        action: 'generate_commit_message',
      })
      if (result.message) setMessage(result.message)
    } catch (error) {
      useToastStore.getState().push({
        tone: 'error',
        title: 'Could not generate commit message',
        description: error instanceof Error ? error.message : undefined,
      })
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="shrink-0 border-t border-(--color-border) bg-(--bg-card) p-2">
      <div className="overflow-hidden rounded-lg border border-(--color-border) bg-(--bg-base) focus-within:border-(--color-accent)">
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleCommit() }}
          placeholder={stagedCount > 0 ? 'Describe these changes…' : 'Stage files to create a commit'}
          rows={2}
          className="block w-full resize-none bg-transparent px-3 py-2 text-xs leading-5 text-(--color-text) outline-none placeholder:text-(--color-text-subtle)"
        />
        <div className="flex items-center gap-2 border-t border-(--color-border) bg-(--bg-key)/25 px-2 py-1.5">
          <span className={cn(
            'rounded-full px-2 py-0.5 text-[9px] font-medium',
            stagedCount > 0 ? 'bg-(--color-accent)/15 text-(--color-accent)' : 'bg-(--bg-key) text-(--color-text-subtle)',
          )}>
            {stagedCount} staged
          </span>
          <label className="flex items-center gap-1 text-[10px] text-(--color-text-muted)">
            <input type="checkbox" checked={amend} onChange={() => setAmend(!amend)} className="h-3 w-3 accent-(--color-accent)" />
            Amend
          </label>
          <span className="hidden text-[9px] text-(--color-text-subtle) sm:inline">⌘ Enter to commit</span>
          <div className="flex-1" />
          <button
            type="button"
            onClick={() => { void generateMessage() }}
            disabled={!sessionId || generating || stagedCount === 0}
            className="flex h-7 items-center gap-1.5 rounded-md px-2 text-[10px] font-medium text-(--color-accent) hover:bg-(--bg-key) disabled:opacity-40"
          >
            {generating ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />}
            Generate message
          </button>
          <button
            type="button"
            onClick={handleCommit}
            disabled={commitMutation.isPending || (!message.trim() && !amend) || (stagedCount === 0 && !amend)}
            className="flex h-7 items-center gap-1.5 rounded-md bg-(--color-accent) px-3 text-[11px] font-semibold text-(--color-text-on-accent) transition-colors hover:bg-(--color-accent)/90 disabled:opacity-40"
          >
            {commitMutation.isPending ? <Loader2 size={11} className="animate-spin" /> : <GitCommit size={11} />}
            {amend ? 'Amend' : 'Commit'}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ── File List Panel ─────────────────────────────────────────────────────── */

function FileListPanel({ workspace, stagedFiles, unstagedFiles, isLoading, selectedPath, onSelect }: {
  workspace: string; stagedFiles: ChangedFile[]; unstagedFiles: ChangedFile[]; isLoading: boolean; selectedPath: string | null; onSelect: (path: string) => void
}) {
  const [filter, setFilter] = useState('')
  const stageMutation = useGitStageMutation(workspace)
  const unstageMutation = useGitUnstageMutation(workspace)
  const discardMutation = useGitDiscardMutation(workspace)

  const allFiles = [...stagedFiles, ...unstagedFiles]
  const filtered = filter ? allFiles.filter((f) => f.path.toLowerCase().includes(filter.toLowerCase())) : allFiles
  const filteredStaged = filtered.filter((f) => f.staged)
  const filteredUnstaged = filtered.filter((f) => !f.staged)

  if (isLoading) return <div className="flex w-[42%] min-w-56 max-w-80 shrink-0 items-center justify-center border-r border-(--color-border)"><Loader2 size={14} className="animate-spin text-(--color-text-subtle)" /></div>

  return (
    <div className="flex w-[42%] min-w-56 max-w-80 shrink-0 flex-col border-r border-(--color-border) bg-(--bg-card)/30">
      <div className="flex h-9 items-center gap-2 border-b border-(--color-border) px-2">
        <Search size={12} className="shrink-0 text-(--color-text-subtle)" />
        <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={`Filter ${allFiles.length} changed files…`} className="min-w-0 flex-1 bg-transparent text-[11px] text-(--color-text) outline-none placeholder:text-(--color-text-subtle)" />
        {filter && <button type="button" onClick={() => setFilter('')} className="text-(--color-text-subtle) hover:text-(--color-text)"><X size={10} /></button>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {filteredStaged.length > 0 && (
          <div>
            <div className="sticky top-0 z-10 flex h-8 items-center justify-between bg-(--bg-card) px-3">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">Staged · {filteredStaged.length}</span>
              <button type="button" onClick={() => unstageMutation.mutate(filteredStaged.map((f) => f.path))} className="flex items-center gap-1 rounded px-1.5 py-1 text-[9px] text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)" title="Unstage all"><RotateCcw size={10} /> All</button>
            </div>
            {filteredStaged.map((file) => <FileRow key={file.path} file={file} selected={selectedPath === file.path} onSelect={() => onSelect(file.path)} onToggleStage={() => unstageMutation.mutate([file.path])} />)}
          </div>
        )}
        {filteredUnstaged.length > 0 && (
          <div>
            <div className="sticky top-0 z-10 flex h-8 items-center justify-between bg-(--bg-card) px-3">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">Unstaged · {filteredUnstaged.length}</span>
              <button type="button" onClick={() => stageMutation.mutate(filteredUnstaged.map((f) => f.path))} className="flex items-center gap-1 rounded px-1.5 py-1 text-[9px] text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)" title="Stage all"><Plus size={10} /> All</button>
            </div>
            {filteredUnstaged.map((file) => <FileRow key={file.path} file={file} selected={selectedPath === file.path} onSelect={() => onSelect(file.path)} onToggleStage={() => stageMutation.mutate([file.path])} onDiscard={() => discardMutation.mutate([file.path])} />)}
          </div>
        )}
        {filtered.length === 0 && <div className="flex flex-col items-center justify-center py-8 text-center"><p className="text-[11px] text-(--color-text-subtle)">{filter ? 'No matching files' : 'No changes'}</p></div>}
      </div>
    </div>
  )
}

function FileRow({ file, selected, onSelect, onToggleStage, onDiscard }: {
  file: ChangedFile; selected: boolean; onSelect: () => void; onToggleStage: () => void; onDiscard?: () => void
}) {
  const badge = STATUS_BADGE[file.status] ?? { label: '?', cls: 'bg-(--bg-key) text-(--color-text-muted)' }
  const name = fileName(file.path)
  const parent = parentPath(file.path)
  const actions: GitAction[] = [
    { label: 'View diff', icon: <FileDiff size={12} />, onSelect },
    {
      label: file.staged ? 'Unstage file' : 'Stage file',
      icon: file.staged ? <RotateCcw size={12} /> : <Plus size={12} />,
      onSelect: onToggleStage,
    },
    {
      label: 'Copy relative path',
      icon: <Copy size={12} />,
      onSelect: () => {
        void navigator.clipboard.writeText(file.path)
        useToastStore.getState().push({ tone: 'info', title: 'File path copied' })
      },
      separatorBefore: true,
    },
  ]
  if (onDiscard) {
    const discardLabel = file.status === 'untracked' ? 'Delete untracked file' : 'Discard changes'
    actions.push({
      label: discardLabel,
      icon: <RotateCcw size={12} />,
      onSelect: () => {
        const warning = file.status === 'untracked'
          ? `Delete untracked file ${file.path}? This cannot be undone.`
          : `Discard all unstaged changes in ${file.path}? This cannot be undone.`
        if (window.confirm(warning)) onDiscard()
      },
      danger: true,
      separatorBefore: true,
    })
  }
  return (
    <GitActionSurface
      label={file.path}
      actions={actions}
      className={cn(
        'group flex cursor-pointer items-center gap-2 border-l-2 px-2.5 py-1.5 text-left transition-colors',
        selected
          ? 'border-(--color-accent) bg-(--color-accent)/10'
          : 'border-transparent hover:bg-(--bg-key)',
      )}
      onClick={onSelect}
      onOpenMenu={onSelect}
    >
      <button type="button" onClick={(e) => { e.stopPropagation(); onToggleStage() }} className={cn('flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors', file.staged ? 'border-(--color-accent) bg-(--color-accent) text-(--color-text-on-accent)' : 'border-(--color-border) bg-(--bg-base) hover:border-(--color-accent)')} aria-label={file.staged ? 'Unstage' : 'Stage'}>
        {file.staged && <Check size={10} />}
      </button>
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="truncate font-mono text-[11px] font-medium text-(--color-text)" title={file.path}>{name}</span>
          <span className={cn('flex h-4 min-w-4 shrink-0 items-center justify-center rounded px-1 text-[8px] font-bold', badge.cls)}>{badge.label}</span>
        </span>
        <span className="block truncate font-mono text-[9px] text-(--color-text-subtle)">
          {file.old_path ? `${fileName(file.old_path)} → ${parent || '.'}` : parent || '.'}
        </span>
      </span>
    </GitActionSurface>
  )
}

/* ───────────────────────────────────────────────────────────────────────────
   Diff Panel — unified diff like GitHub / VS Code / IntelliJ
   ─────────────────────────────────────────────────────────────────────────── */

function DiffPanel({ workspace, path }: { workspace: string; path: string | null }) {
  const diffQuery = useGitDiffViewQuery(workspace, path, !!path)
  const rawDiff = diffQuery.data?.diff ?? ''
  // MUST call useMemo before any early return (React hooks rule)
  const hunks = useMemo(() => parseUnifiedDiff(rawDiff), [rawDiff])

  if (!path) return <div className="flex flex-1 items-center justify-center text-[11px] text-(--color-text-subtle)">Select a file to view diff</div>
  if (diffQuery.isLoading) return <div className="flex flex-1 items-center justify-center"><Loader2 size={14} className="animate-spin text-(--color-text-subtle)" /></div>

  if (!rawDiff || hunks.length === 0) {
    return (
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <DiffHeader path={path} />
        <div className="flex flex-1 items-center justify-center text-[11px] text-(--color-text-subtle)">No changes</div>
      </div>
    )
  }

  // Compute total added/removed lines
  let totalAdded = 0
  let totalRemoved = 0
  for (const hunk of hunks) {
    for (const line of hunk.lines) {
      if (line.type === 'add') totalAdded++
      if (line.type === 'del') totalRemoved++
    }
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
      <DiffHeader path={path} added={totalAdded} removed={totalRemoved} />
      <div className="min-h-0 flex-1 overflow-auto bg-(--bg-base)">
        <pre className="font-mono text-[11px] leading-[18px]">
          {hunks.map((hunk, hi) => (
            <DiffHunk key={hi} hunk={hunk} hunkIndex={hi} />
          ))}
        </pre>
      </div>
    </div>
  )
}

function DiffHeader({ path, added, removed }: { path: string; added?: number; removed?: number }) {
  return (
    <div className="flex shrink-0 items-center gap-2 border-b border-(--color-border) bg-(--bg-key)/50 px-3 py-1">
      <span className="truncate font-mono text-[11px] text-(--color-text)">{path}</span>
      <div className="flex-1" />
      {added != null && removed != null && (
        <div className="flex items-center gap-2 text-[10px]">
          <span className="text-green-400">+{added}</span>
          <span className="text-red-400">-{removed}</span>
        </div>
      )}
    </div>
  )
}

/**
 * Render a single diff hunk in GitHub-style unified format.
 *
 * Layout per line:
 *   [gutter: line numbers] [sign: + / - / space] [content]
 *
 * Colors:
 *   additions → green background
 *   deletions → red background
 *   context   → neutral
 *   hunk header → blue/gray
 */
function DiffHunk({ hunk, hunkIndex }: { hunk: DiffHunk; hunkIndex: number }) {
  let oldLine = hunk.oldStart
  let newLine = hunk.newStart

  // Count lines for initial line numbers display
  const lines: { oldNum: number | null; newNum: number | null; type: DiffLine['type']; content: string }[] = []

  for (const line of hunk.lines) {
    switch (line.type) {
      case 'del':
        lines.push({ oldNum: oldLine++, newNum: null, type: 'del', content: line.content })
        break
      case 'add':
        lines.push({ oldNum: null, newNum: newLine++, type: 'add', content: line.content })
        break
      case 'ctx':
        lines.push({ oldNum: oldLine++, newNum: newLine++, type: 'ctx', content: line.content })
        break
      case 'info':
        lines.push({ oldNum: null, newNum: null, type: 'info', content: line.content })
        break
    }
  }

  return (
    <>
      {/* Hunk header */}
      <div className="border-t border-(--color-border)/50 bg-blue-500/5 px-3 py-0.5 text-[10px] text-blue-400/80">
        {hunk.header}
      </div>
      {/* Lines */}
      {lines.map((l, i) => (
        <DiffLine key={`${hunkIndex}-${i}`} {...l} />
      ))}
    </>
  )
}

/**
 * Single diff line — GitHub/VS Code style.
 *
 *   ┌────────┬─────┬──────────────────────────────────┐
 *   │ oldNum │newNum│ +/- │ content                     │
 *   └────────┴─────┴──────────────────────────────────┘
 */
function DiffLine({ oldNum, newNum, type, content }: {
  oldNum: number | null; newNum: number | null; type: DiffLine['type']; content: string
}) {
  const bgCls = type === 'add'
    ? 'bg-green-500/[0.08]'
    : type === 'del'
      ? 'bg-red-500/[0.08]'
      : ''

  const signCls = type === 'add'
    ? 'text-green-400'
    : type === 'del'
      ? 'text-red-400'
      : 'text-transparent'

  const sign = type === 'add' ? '+' : type === 'del' ? '-' : ' '

  return (
    <div className={cn('flex', bgCls)}>
      {/* Old line number */}
      <span className="w-10 shrink-0 select-none border-r border-(--color-border)/35 px-1 text-right text-[9px] text-(--color-text-subtle)/60">
        {oldNum ?? ''}
      </span>
      {/* New line number */}
      <span className="w-10 shrink-0 select-none border-r border-(--color-border)/35 px-1 text-right text-[9px] text-(--color-text-subtle)/60">
        {newNum ?? ''}
      </span>
      {/* Sign */}
      <span className={cn('w-5 shrink-0 select-none text-center text-[11px] font-medium', signCls)}>
        {sign}
      </span>
      {/* Content */}
      <span className="min-w-0 flex-1 whitespace-pre px-1 text-(--color-text)">{content || ' '}</span>
    </div>
  )
}

/* ── Branches Panel — SourceTree style ──────────────────────────────────── */

function BranchesPanel({ workspace }: { workspace: string }) {
  const [newBranch, setNewBranch] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const branchesQuery = useGitBranchesQuery(workspace)
  const checkoutMutation = useGitCheckoutMutation(workspace)
  const createBranchMutation = useGitCreateBranchMutation(workspace)
  const deleteBranchMutation = useGitDeleteBranchMutation(workspace)
  const mergeMutation = useGitMergeMutation(workspace)
  const rebaseMutation = useGitRebaseMutation(workspace)
  const branches = branchesQuery.data ?? []
  const localBranches = branches.filter((b) => !b.remote)
  const remoteBranches = branches.filter((b) => b.remote && !b.name.endsWith('/HEAD'))
  const busy = checkoutMutation.isPending || createBranchMutation.isPending || deleteBranchMutation.isPending || mergeMutation.isPending || rebaseMutation.isPending

  if (branchesQuery.isLoading) {
    return <div className="flex items-center justify-center py-6"><Loader2 size={14} className="animate-spin text-(--color-text-subtle)" /></div>
  }

  return (
    <div className="flex min-h-0 flex-1">
      {/* Branch list */}
      <div className="min-w-0 flex-1 overflow-y-auto">
        {/* Toolbar */}
        <div className="flex items-center justify-between border-b border-(--color-border) px-3 py-1.5">
          <div className="flex items-center gap-1.5">
            <GitBranch size={12} className="text-(--color-text-subtle)" />
            <span className="text-[11px] font-medium text-(--color-text)">Local Branches</span>
            <span className="rounded bg-(--bg-key) px-1.5 py-0.5 text-[9px] text-(--color-text-subtle)">{localBranches.length}</span>
          </div>
          <button type="button" onClick={() => setShowCreate(!showCreate)} className="flex items-center gap-1 rounded px-2 py-0.5 text-[10px] text-(--color-accent) hover:bg-(--bg-key)" title="Create new branch">
            <Plus size={11} /> New
          </button>
        </div>

        {/* Create form */}
        {showCreate && (
          <div className="flex items-center gap-1.5 border-b border-(--color-border) px-3 py-2">
            <input
              value={newBranch}
              onChange={(e) => setNewBranch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && newBranch.trim()) createBranchMutation.mutate(newBranch.trim(), { onSuccess: () => { setNewBranch(''); setShowCreate(false) } })
                if (e.key === 'Escape') { setShowCreate(false); setNewBranch('') }
              }}
              placeholder="branch-name"
              className="flex-1 rounded border border-(--color-border) bg-(--bg-key) px-2 py-1 text-[11px] text-(--color-text) outline-none focus:border-(--color-accent)"
              autoFocus
            />
            <button type="button" onClick={() => { if (newBranch.trim()) createBranchMutation.mutate(newBranch.trim(), { onSuccess: () => { setNewBranch(''); setShowCreate(false) } }) }} disabled={busy || !newBranch.trim()} className="rounded bg-(--color-accent) px-2 py-0.5 text-[10px] font-medium text-(--color-text-on-accent) disabled:opacity-50">Create</button>
          </div>
        )}

        {/* Branch list */}
        <div className="divide-y divide-(--color-border)/30">
          {localBranches.map((b) => (
            <BranchRow key={b.name} branch={b} busy={busy} onCheckout={() => checkoutMutation.mutate(b.name)} onDelete={() => deleteBranchMutation.mutate({ name: b.name })} onMerge={() => mergeMutation.mutate(b.name)} onRebase={() => rebaseMutation.mutate(b.name)} />
          ))}
          {localBranches.length === 0 && (
            <div className="flex items-center justify-center py-6 text-[11px] text-(--color-text-subtle)">No local branches</div>
          )}
        </div>

        <div className="mt-2 border-t border-(--color-border)">
          <div className="flex h-8 items-center gap-1.5 px-3">
            <RadioTower size={11} className="text-(--color-text-subtle)" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">Remote branches</span>
            <span className="rounded bg-(--bg-key) px-1.5 py-0.5 text-[9px] text-(--color-text-subtle)">{remoteBranches.length}</span>
          </div>
          <div className="divide-y divide-(--color-border)/30">
            {remoteBranches.map((remoteBranch) => (
              <BranchRow
                key={remoteBranch.name}
                branch={remoteBranch}
                busy={busy}
                remote
                onCheckout={() => checkoutMutation.mutate({ name: remoteBranch.name, track: true })}
                onMerge={() => mergeMutation.mutate(remoteBranch.name)}
                onRebase={() => rebaseMutation.mutate(remoteBranch.name)}
              />
            ))}
            {remoteBranches.length === 0 && (
              <div className="px-3 py-4 text-center text-[11px] text-(--color-text-subtle)">Fetch a remote to discover its branches</div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function BranchRow({ branch, busy, remote = false, onCheckout, onDelete, onMerge, onRebase }: {
  branch: { name: string; current: boolean; ahead: number; behind: number }
  busy: boolean; remote?: boolean; onCheckout: () => void; onDelete?: () => void; onMerge?: () => void; onRebase?: () => void
}) {
  const actions: GitAction[] = []
  if (!branch.current) {
    actions.push({
      label: remote ? 'Checkout and track' : 'Checkout branch',
      icon: <ArrowRightLeft size={12} />,
      onSelect: onCheckout,
      disabled: busy,
    })
    if (onMerge) actions.push({ label: 'Merge into current branch', icon: <GitMerge size={12} />, onSelect: onMerge, disabled: busy })
    if (onRebase) actions.push({ label: 'Rebase current branch onto this', icon: <GitBranch size={12} />, onSelect: onRebase, disabled: busy })
  }
  actions.push({
    label: 'Copy branch name',
    icon: <Copy size={12} />,
    onSelect: () => {
      void navigator.clipboard.writeText(branch.name)
      useToastStore.getState().push({ tone: 'info', title: 'Branch name copied' })
    },
    separatorBefore: !branch.current,
  })
  if (onDelete) {
    actions.push({
      label: 'Delete local branch',
      icon: <Trash2 size={12} />,
      onSelect: onDelete,
      disabled: busy,
      danger: true,
      separatorBefore: true,
    })
  }
  return (
    <GitActionSurface
      label={branch.name}
      actions={actions}
      className={cn('group flex items-center gap-2 px-3 py-1.5 transition-colors', branch.current ? 'bg-(--color-accent)/5' : 'hover:bg-(--bg-key)')}
    >
      {/* Branch indicator */}
      <div className={cn('h-3 w-3 shrink-0 rounded-full border-2', branch.current ? 'border-green-400 bg-green-400/30' : 'border-(--color-text-subtle)/50 bg-transparent')} />

      {/* Branch name */}
      <span className={cn('min-w-0 flex-1 truncate font-mono text-[11px]', branch.current ? 'text-green-400 font-medium' : 'text-(--color-text)')}>
        {branch.name}
      </span>

      {/* Current badge */}
      {branch.current && (
        <span className="shrink-0 rounded bg-green-500/20 px-1.5 py-0.5 text-[9px] font-medium text-green-400">HEAD</span>
      )}

      {/* Ahead/behind */}
      {!branch.current && branch.ahead > 0 && (
        <span className="shrink-0 text-[10px] text-green-400">↑{branch.ahead}</span>
      )}
      {!branch.current && branch.behind > 0 && (
        <span className="shrink-0 text-[10px] text-amber-400">↓{branch.behind}</span>
      )}

    </GitActionSurface>
  )
}

/* ── History Panel — Git Graph / SourceTree style ──────────────────────── */

const GRAPH_COLORS = ['#3b82f6', '#22c55e', '#a855f7', '#f59e0b', '#ec4899', '#06b6d4', '#f97316', '#14b8a6']
const HISTORY_BATCH_SIZE = 100
const HISTORY_ROW_HEIGHT = 48
const GRAPH_LANE_GAP = 14
const GRAPH_MAX_VISIBLE_LANES = 10

interface GraphSegment {
  from: number
  to: number
  color: number
}

interface CommitGraphLayout {
  lane: number
  hasIncoming: boolean
  passThrough: GraphSegment[]
  parentLanes: number[]
  outgoingLanes: number[]
  maxLanes: number
}

function buildCommitGraph(entries: GitLogEntry[]): CommitGraphLayout[] {
  let lanes: string[] = []
  return entries.map((entry) => {
    let lane = lanes.indexOf(entry.sha)
    const hasIncoming = lane >= 0
    if (lane < 0) {
      lane = lanes.length
      lanes = [...lanes, entry.sha]
    }
    const incoming = [...lanes]
    const outgoing = [...incoming]
    outgoing.splice(lane, 1)

    const parentLanes: number[] = []
    let insertAt = lane
    for (const parent of entry.parent_shas) {
      let parentLane = outgoing.indexOf(parent)
      if (parentLane < 0) {
        outgoing.splice(insertAt, 0, parent)
        parentLane = insertAt
        insertAt += 1
      }
      parentLanes.push(parentLane)
    }

    const passThrough = incoming.flatMap<GraphSegment>((sha, from) => {
      if (from === lane) return []
      const to = outgoing.indexOf(sha)
      return to < 0 ? [] : [{ from, to, color: from }]
    })
    lanes = outgoing
    return {
      lane,
      hasIncoming,
      passThrough,
      parentLanes,
      outgoingLanes: outgoing.map((_, index) => index),
      maxLanes: Math.max(incoming.length, outgoing.length, 1),
    }
  })
}

function graphLaneX(lane: number, width: number): number {
  return Math.min(12 + lane * GRAPH_LANE_GAP, width - 10)
}

function graphColor(lane: number): string {
  return GRAPH_COLORS[lane % GRAPH_COLORS.length]
}

function refTone(ref: string): string {
  if (ref.startsWith('HEAD')) return 'border-(--color-accent)/40 bg-(--color-accent)/12 text-(--color-accent)'
  if (ref.startsWith('tag: ')) return 'border-green-500/35 bg-green-500/10 text-green-500'
  if (ref.includes('/')) return 'border-purple-500/30 bg-purple-500/10 text-purple-500'
  return 'border-amber-500/35 bg-amber-500/10 text-amber-500'
}

function HistoryPanel({ workspace }: { workspace: string }) {
  const [scope, setScope] = useState<'all' | 'current'>('all')
  const [expandedSha, setExpandedSha] = useState<string | null>(null)
  const logQuery = useGitLogQuery(workspace, { allBranches: scope === 'all' })
  const logFilesQuery = useGitLogFilesQuery(workspace, expandedSha, !!expandedSha)
  const cherryPickMutation = useGitCherryPickMutation(workspace)
  const revertMutation = useGitRevertMutation(workspace)
  const sessionId = useTeamStore((state) => state.sessionId)
  const [aiResult, setAiResult] = useState<GitAIResponse | null>(null)
  const entries = useMemo(
    () => logQuery.data?.pages.flatMap((page) => page.entries) ?? [],
    [logQuery.data?.pages],
  )
  const graph = useMemo(() => buildCommitGraph(entries), [entries])
  const graphWidth = useMemo(() => {
    const lanes = Math.min(
      GRAPH_MAX_VISIBLE_LANES,
      Math.max(1, ...graph.map((row) => row.maxLanes)),
    )
    return 22 + lanes * GRAPH_LANE_GAP
  }, [graph])

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex shrink-0 items-center gap-2 border-b border-(--color-border) px-3 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-1.5">
          <History size={13} className="shrink-0 text-(--color-text-subtle)" />
          <span className="truncate text-[11px] font-semibold text-(--color-text)">Commit history</span>
          {entries.length > 0 && (
            <span className="shrink-0 rounded-full bg-(--bg-key) px-1.5 py-0.5 text-[9px] text-(--color-text-subtle)">
              {entries.length}{logQuery.hasNextPage ? '+' : ''}
            </span>
          )}
        </div>
        <div className="flex shrink-0 rounded-md bg-(--bg-key) p-0.5" aria-label="History scope">
          {(['all', 'current'] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => {
                setScope(value)
                setExpandedSha(null)
              }}
              className={cn(
                'rounded px-2 py-1 text-[9px] font-medium transition-colors',
                scope === value
                  ? 'bg-(--bg-card) text-(--color-text) shadow-sm'
                  : 'text-(--color-text-subtle) hover:text-(--color-text)',
              )}
            >
              {value === 'all' ? 'All branches' : 'Current'}
            </button>
          ))}
        </div>
      </div>

      {logQuery.isLoading ? (
        <div className="flex items-center justify-center py-8"><Loader2 size={14} className="animate-spin text-(--color-text-subtle)" /></div>
      ) : logQuery.isError ? (
        <div className="flex flex-col items-center justify-center gap-2 py-8 text-[11px] text-(--color-text-subtle)">
          <span>Unable to load commit history</span>
          <button type="button" onClick={() => void logQuery.refetch()} className="rounded-md border border-(--color-border) px-2 py-1 text-(--color-text-muted) hover:bg-(--bg-key)">Retry</button>
        </div>
      ) : entries.length === 0 ? (
        <div className="flex items-center justify-center py-8 text-[11px] text-(--color-text-subtle)">No commits</div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto">
          {entries.map((entry, idx) => (
            <CommitRow
              key={entry.sha}
              entry={entry}
              layout={graph[idx]}
              graphWidth={graphWidth}
              isHead={entry.refs.some((ref) => ref.startsWith('HEAD'))}
              isExpanded={expandedSha === entry.sha}
              onToggle={() => setExpandedSha(expandedSha === entry.sha ? null : entry.sha)}
              onCherryPick={() => cherryPickMutation.mutate([entry.sha], {
                onSuccess: (data) => {
                  if (data.success) useToastStore.getState().push({ tone: 'success', title: 'Cherry-picked' })
                  else useToastStore.getState().push({ tone: 'error', title: 'Conflicts', description: data.conflicts.join(', ') })
                },
              })}
              onRevert={() => revertMutation.mutate(entry.sha, {
                onSuccess: (data) => {
                  if (data.success) useToastStore.getState().push({ tone: 'success', title: 'Commit reverted' })
                  else useToastStore.getState().push({ tone: 'error', title: 'Revert needs resolution', description: data.conflicts.join(', ') })
                },
                onError: (error) => useToastStore.getState().push({ tone: 'error', title: 'Unable to revert commit', description: error instanceof Error ? error.message : undefined }),
              })}
              onExplain={() => {
                if (!sessionId) {
                  useToastStore.getState().push({
                    tone: 'info',
                    title: 'Open a coding task to explain commits with AI',
                    description: 'The active task supplies the model and workspace authorization.',
                  })
                  return
                }
                void runGitAIAction(workspace, {
                  session_id: sessionId,
                  action: 'explain_commit',
                  reference: entry.sha,
                }).then(setAiResult).catch((error: unknown) => {
                  useToastStore.getState().push({
                    tone: 'error',
                    title: 'Could not explain commit',
                    description: error instanceof Error ? error.message : undefined,
                  })
                })
              }}
              filesQuery={logFilesQuery}
              isFilesLoading={logFilesQuery.isLoading && expandedSha === entry.sha}
              files={expandedSha === entry.sha ? (logFilesQuery.data ?? []) : []}
            />
          ))}
          <div className="flex items-center justify-center border-t border-(--color-border)/70 px-3 py-3">
            {logQuery.hasNextPage ? (
              <button
                type="button"
                onClick={() => void logQuery.fetchNextPage()}
                disabled={logQuery.isFetchingNextPage}
                className="inline-flex min-w-40 items-center justify-center gap-1.5 rounded-md border border-(--color-border) bg-(--bg-card) px-3 py-1.5 text-[10px] font-medium text-(--color-text-muted) shadow-sm hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-60"
              >
                {logQuery.isFetchingNextPage && <Loader2 size={11} className="animate-spin" />}
                Load {HISTORY_BATCH_SIZE} older commits
              </button>
            ) : (
              <span className="text-[9px] text-(--color-text-subtle)">Complete history · {entries.length} commits loaded</span>
            )}
          </div>
          {aiResult && <GitAiResultDialog result={aiResult} onClose={() => setAiResult(null)} />}
        </div>
      )}
    </div>
  )
}

/* ── Single Commit Row with Graph ────────────────────────────────────────── */

function CommitRow({
  entry, layout, graphWidth, isHead, isExpanded,
  onToggle, onCherryPick, onRevert, onExplain, isFilesLoading, files,
}: {
  entry: GitLogEntry
  layout: CommitGraphLayout
  graphWidth: number
  isHead: boolean
  isExpanded: boolean
  onToggle: () => void; onCherryPick: () => void; onRevert: () => void; onExplain: () => void
  filesQuery: ReturnType<typeof useGitLogFilesQuery>
  isFilesLoading: boolean
  files: { path: string; status: string }[]
}) {
  const isMerge = entry.parent_shas.length > 1
  const nodeX = graphLaneX(layout.lane, graphWidth)
  const actions: GitAction[] = [
    {
      label: isExpanded ? 'Hide changed files' : 'Show changed files',
      icon: <FileDiff size={12} />,
      onSelect: onToggle,
    },
    {
      label: 'Explain commit with AI',
      icon: <Sparkles size={12} />,
      onSelect: onExplain,
      separatorBefore: true,
    },
    {
      label: 'Copy full commit SHA',
      icon: <Copy size={12} />,
      onSelect: () => {
        void navigator.clipboard.writeText(entry.sha)
        useToastStore.getState().push({ tone: 'info', title: 'SHA copied' })
      },
      separatorBefore: true,
    },
    {
      label: 'Cherry-pick commit',
      icon: <GitCommit size={12} />,
      onSelect: onCherryPick,
    },
    {
      label: 'Revert commit',
      icon: <RotateCcw size={12} />,
      onSelect: onRevert,
      separatorBefore: true,
    },
  ]

  return (
    <div>
      {/* ── Commit Row ── */}
      <GitActionSurface
        label={`${entry.short_sha} ${entry.message}`}
        actions={actions}
        className={cn(
          'group flex cursor-pointer transition-colors',
          isExpanded ? 'bg-(--bg-key)' : 'hover:bg-(--bg-key)/50',
        )}
        style={{ minHeight: HISTORY_ROW_HEIGHT }}
        onClick={onToggle}
      >
        <svg
          className="shrink-0 overflow-visible"
          width={graphWidth}
          height={HISTORY_ROW_HEIGHT}
          viewBox={`0 0 ${graphWidth} ${HISTORY_ROW_HEIGHT}`}
          aria-hidden="true"
        >
          {layout.passThrough.map((segment, index) => {
            const fromX = graphLaneX(segment.from, graphWidth)
            const toX = graphLaneX(segment.to, graphWidth)
            return (
              <path
                key={`pass-${segment.from}-${segment.to}-${index}`}
                d={`M ${fromX} 0 C ${fromX} 14 ${toX} 34 ${toX} ${HISTORY_ROW_HEIGHT}`}
                fill="none"
                stroke={graphColor(segment.color)}
                strokeWidth="2"
              />
            )
          })}
          {layout.hasIncoming && (
            <path d={`M ${nodeX} 0 L ${nodeX} 24`} stroke={graphColor(layout.lane)} strokeWidth="2" />
          )}
          {layout.parentLanes.map((parentLane, index) => {
            const parentX = graphLaneX(parentLane, graphWidth)
            return (
              <path
                key={`${entry.sha}-parent-${index}`}
                d={`M ${nodeX} 24 C ${nodeX} 34 ${parentX} 34 ${parentX} ${HISTORY_ROW_HEIGHT}`}
                fill="none"
                stroke={graphColor(parentLane)}
                strokeWidth="2"
              />
            )
          })}
          <circle
            cx={nodeX}
            cy="24"
            r={isHead ? 6 : isMerge ? 5 : 4}
            fill={isHead ? 'var(--color-accent)' : 'var(--bg-card)'}
            stroke={isHead ? 'var(--color-accent)' : graphColor(layout.lane)}
            strokeWidth={isMerge ? 3 : 2}
          />
          {isHead && <circle cx={nodeX} cy="24" r="2" fill="white" />}
        </svg>

        <div className="min-w-0 flex-1 py-1.5 pr-1">
          <div className="flex min-w-0 items-center gap-1.5">
            <p className="min-w-0 flex-1 truncate text-[11px] font-medium text-(--color-text) leading-tight">
              {entry.message}
            </p>
            {isMerge && (
              <span className="shrink-0 rounded bg-green-500/20 px-1.5 py-0.5 text-[8px] font-medium text-green-400 leading-none">merge</span>
            )}
          </div>
          <div className="mt-1 flex min-w-0 items-center gap-1.5 text-[9px] text-(--color-text-subtle)">
            <span
              className="cursor-pointer rounded bg-(--bg-key) px-1 py-0.5 font-mono text-[8px] text-(--color-accent) transition-colors hover:bg-(--color-accent)/20"
              onClick={(e) => {
                e.stopPropagation()
                void navigator.clipboard.writeText(entry.sha)
                useToastStore.getState().push({ tone: 'info', title: 'SHA copied' })
              }}
              title="Copy full SHA"
            >
              {entry.short_sha}
            </span>
            <span>{entry.author}</span>
            <span>·</span>
            <span className="shrink-0">{formatDate(entry.date)}</span>
            {entry.refs.slice(0, 3).map((ref) => (
              <span
                key={ref}
                className={cn('max-w-32 shrink truncate rounded border px-1 py-0.5 font-mono text-[8px]', refTone(ref))}
                title={ref}
              >
                {ref}
              </span>
            ))}
            {entry.refs.length > 3 && (
              <span className="shrink-0 text-[8px] text-(--color-text-subtle)">+{entry.refs.length - 3}</span>
            )}
          </div>
        </div>

      </GitActionSurface>

      {/* ── Expanded: files changed ── */}
      {isExpanded && (
        <div className="flex">
          <div className="relative shrink-0" style={{ width: graphWidth }}>
            {layout.outgoingLanes.map((lane) => (
              <span
                key={lane}
                className="absolute inset-y-0 w-0.5"
                style={{
                  left: graphLaneX(lane, graphWidth) - 1,
                  backgroundColor: graphColor(lane),
                }}
              />
            ))}
          </div>
          <div className="min-w-0 flex-1 border-t border-(--color-border)/50 bg-(--bg-key)/30 px-3 py-2">
            {isFilesLoading ? (
              <div className="flex items-center gap-1.5 py-1 text-[10px] text-(--color-text-subtle)">
                <Loader2 size={10} className="animate-spin" /> Loading files…
              </div>
            ) : files.length === 0 ? (
              <p className="text-[10px] text-(--color-text-subtle)">No file changes</p>
            ) : (
              <div className="space-y-0.5">
                {files.map((f) => {
                  const s = STATUS_BADGE[f.status] ?? { label: '?', cls: 'bg-(--bg-key) text-(--color-text-muted)' }
                  return (
                    <div key={f.path} className="flex items-center gap-1.5">
                      <span className={cn('flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded text-[8px] font-bold', s.cls)}>{s.label}</span>
                      <span className="truncate font-mono text-[10px] text-(--color-text)">{f.path}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Stash Panel ─────────────────────────────────────────────────────────── */

function StashPanel({ workspace }: { workspace: string }) {
  const [showCreate, setShowCreate] = useState(false)
  const [message, setMessage] = useState('')
  const stashesQuery = useGitStashesQuery(workspace)
  const createMutation = useGitStashCreateMutation(workspace)
  const applyMutation = useGitStashApplyMutation(workspace)
  const popMutation = useGitStashPopMutation(workspace)
  const dropMutation = useGitStashDropMutation(workspace)
  const stashes = stashesQuery.data ?? []
  const busy = applyMutation.isPending || popMutation.isPending || dropMutation.isPending

  if (stashesQuery.isLoading) {
    return <div className="flex items-center justify-center py-6"><Loader2 size={14} className="animate-spin text-(--color-text-subtle)" /></div>
  }

  return (
    <div className="flex min-h-0 flex-1">
      <div className="min-w-0 flex-1 overflow-y-auto">
        {/* Toolbar */}
        <div className="flex items-center justify-between border-b border-(--color-border) px-3 py-1.5">
          <div className="flex items-center gap-1.5">
            <Archive size={12} className="text-(--color-text-subtle)" />
            <span className="text-[11px] font-medium text-(--color-text)">Stashes</span>
            {stashes.length > 0 && <span className="rounded bg-(--bg-key) px-1.5 py-0.5 text-[9px] text-(--color-text-subtle)">{stashes.length}</span>}
          </div>
          <button type="button" onClick={() => setShowCreate(!showCreate)} className="flex items-center gap-1 rounded px-2 py-0.5 text-[10px] text-(--color-accent) hover:bg-(--bg-key)" title="Stash current changes">
            <Plus size={11} /> New
          </button>
        </div>

        {/* Create form */}
        {showCreate && (
          <div className="flex items-center gap-1.5 border-b border-(--color-border) px-3 py-2">
            <input
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && message.trim()) createMutation.mutate({ message: message.trim() || undefined }, { onSuccess: () => { setMessage(''); setShowCreate(false) } })
                if (e.key === 'Escape') { setShowCreate(false); setMessage('') }
              }}
              placeholder="Stash message (optional)"
              className="flex-1 rounded border border-(--color-border) bg-(--bg-key) px-2 py-1 text-[11px] text-(--color-text) outline-none focus:border-(--color-accent)"
              autoFocus
            />
            <button type="button" onClick={() => createMutation.mutate({ message: message.trim() || undefined }, { onSuccess: () => { setMessage(''); setShowCreate(false) } })} disabled={createMutation.isPending} className="rounded bg-(--color-accent) px-2 py-0.5 text-[10px] font-medium text-(--color-text-on-accent) disabled:opacity-50">Stash</button>
          </div>
        )}

        {/* Stash list */}
        <div className="divide-y divide-(--color-border)/30">
          {stashes.map((stash) => {
            const actions: GitAction[] = [
              { label: 'Apply stash', icon: <Play size={12} />, onSelect: () => applyMutation.mutate(stash.index), disabled: busy },
              { label: 'Pop stash', icon: <ArrowUpFromLine size={12} />, onSelect: () => popMutation.mutate(stash.index), disabled: busy },
              {
                label: 'Copy stash SHA',
                icon: <Copy size={12} />,
                onSelect: () => {
                  void navigator.clipboard.writeText(stash.sha)
                  useToastStore.getState().push({ tone: 'info', title: 'Stash SHA copied' })
                },
                separatorBefore: true,
              },
              { label: 'Drop stash', icon: <Trash2 size={12} />, onSelect: () => dropMutation.mutate(stash.index), disabled: busy, danger: true, separatorBefore: true },
            ]
            return (
            <GitActionSurface key={stash.index} label={stash.message} actions={actions} className="flex items-center gap-2 px-3 py-1.5 hover:bg-(--bg-key)">
              <Archive size={11} className="shrink-0 text-(--color-text-subtle)" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[11px] text-(--color-text)">{stash.message}</p>
                <p className="font-mono text-[9px] text-(--color-text-subtle)">{stash.sha}</p>
              </div>
            </GitActionSurface>
            )
          })}
          {stashes.length === 0 && (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <Archive size={20} className="mb-2 text-(--color-text-subtle) opacity-40" />
              <p className="text-[11px] text-(--color-text-subtle)">No stashed changes</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/* ── Remotes Panel ───────────────────────────────────────────────────────── */

function RemotesPanel({
  workspace,
  branch,
  upstream,
  userName,
  userEmail,
}: {
  workspace: string
  branch: string | null | undefined
  upstream: string | null
  userName: string | null
  userEmail: string | null
}) {
  const remotesQuery = useGitRemotesQuery(workspace)
  const createMutation = useGitCreateRemoteMutation(workspace)
  const updateMutation = useGitUpdateRemoteMutation(workspace)
  const deleteMutation = useGitDeleteRemoteMutation(workspace)
  const fetchMutation = useGitFetchMutation(workspace)
  const pullMutation = useGitPullMutation(workspace)
  const pushMutation = useGitPushMutation(workspace)
  const identityMutation = useGitSetIdentityMutation(workspace)
  const remotes = useMemo(() => remotesQuery.data ?? [], [remotesQuery.data])
  const [showForm, setShowForm] = useState(false)
  const [editingName, setEditingName] = useState<string | null>(null)
  const [name, setName] = useState('origin')
  const [url, setUrl] = useState('')
  const [selectedRemote, setSelectedRemote] = useState('origin')
  const [prune, setPrune] = useState(true)
  const [rebase, setRebase] = useState(false)
  const [forceWithLease, setForceWithLease] = useState(false)
  const [showIdentity, setShowIdentity] = useState(false)
  const [identityName, setIdentityName] = useState(userName ?? '')
  const [identityEmail, setIdentityEmail] = useState(userEmail ?? '')
  const busy = createMutation.isPending || updateMutation.isPending || deleteMutation.isPending

  useEffect(() => {
    if (remotes.length > 0 && !remotes.some((item) => item.name === selectedRemote)) {
      setSelectedRemote(remotes[0].name) // eslint-disable-line react-hooks/set-state-in-effect -- synchronize remote selection with server data
    }
  }, [remotes, selectedRemote])

  useEffect(() => {
    if (!showIdentity) {
      setIdentityName(userName ?? '') // eslint-disable-line react-hooks/set-state-in-effect -- synchronize form with repository config
      setIdentityEmail(userEmail ?? '')
    }
  }, [showIdentity, userEmail, userName])

  const resetForm = () => {
    setShowForm(false)
    setEditingName(null)
    setName('origin')
    setUrl('')
  }

  const submitRemote = () => {
    if (!name.trim() || !url.trim()) return
    const input = { name: editingName ?? name.trim(), url: url.trim() }
    const options = {
      onSuccess: () => {
        useToastStore.getState().push({ tone: 'success', title: editingName ? 'Remote updated' : 'Remote added' })
        resetForm()
      },
      onError: (error: Error) => useToastStore.getState().push({ tone: 'error' as const, title: 'Remote operation failed', description: error.message }),
    }
    if (editingName) updateMutation.mutate(input, options)
    else createMutation.mutate(input, options)
  }

  const startSync = (
    kind: 'fetch' | 'pull' | 'push',
    action: () => void,
  ) => {
    action()
    useToastStore.getState().push({ tone: 'info', title: `${kind.charAt(0).toUpperCase()}${kind.slice(1)} started` })
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="shrink-0 border-b border-(--color-border) bg-(--bg-card)/30 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-(--color-text)">Remote sync</p>
            <p className="mt-0.5 truncate text-[10px] text-(--color-text-subtle)">
              {upstream ? `Tracking ${upstream}` : branch ? `${branch} has no upstream yet` : 'Choose a branch before pushing'}
            </p>
          </div>
          <SelectControl
            value={selectedRemote}
            onValueChange={setSelectedRemote}
            disabled={remotes.length === 0}
            size="sm"
            className="min-w-28 bg-(--bg-card) text-[11px]"
            ariaLabel="Remote for sync"
            options={remotes.length === 0
              ? [{ value: 'origin', label: 'No remotes' }]
              : remotes.map((remote) => ({ value: remote.name, label: remote.name }))}
          />
          <button
            type="button"
            disabled={remotes.length === 0 || fetchMutation.isPending}
            onClick={() => startSync('fetch', () => fetchMutation.mutate({ remote: selectedRemote, prune }))}
            className="flex h-8 items-center gap-1.5 rounded-md border border-(--color-border) bg-(--bg-card) px-2.5 text-[10px] font-medium text-(--color-text-muted) hover:bg-(--bg-key) disabled:opacity-40"
          >
            <CloudDownload size={12} /> Fetch
          </button>
          <button
            type="button"
            disabled={remotes.length === 0 || pullMutation.isPending}
            onClick={() => startSync('pull', () => pullMutation.mutate({ remote: selectedRemote, rebase }))}
            className="flex h-8 items-center gap-1.5 rounded-md border border-(--color-border) bg-(--bg-card) px-2.5 text-[10px] font-medium text-(--color-text-muted) hover:bg-(--bg-key) disabled:opacity-40"
          >
            <RefreshCw size={12} /> Pull
          </button>
          <button
            type="button"
            disabled={remotes.length === 0 || !branch || pushMutation.isPending}
            onClick={() => startSync('push', () => pushMutation.mutate({
              remote: selectedRemote,
              branch: branch ?? undefined,
              setUpstream: !upstream,
              forceWithLease,
            }))}
            className={cn(
              'flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[10px] font-semibold text-(--color-text-on-accent) disabled:opacity-40',
              forceWithLease ? 'bg-(--color-warning)' : 'bg-(--color-accent)',
            )}
          >
            <CloudUpload size={12} /> {forceWithLease ? 'Force push' : 'Push'}
          </button>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-[10px] text-(--color-text-muted)">
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={prune} onChange={(event) => setPrune(event.target.checked)} className="accent-(--color-accent)" /> Prune stale branches on fetch</label>
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={rebase} onChange={(event) => setRebase(event.target.checked)} className="accent-(--color-accent)" /> Rebase on pull</label>
          <label className="flex items-center gap-1.5 text-(--color-warning)"><input type="checkbox" checked={forceWithLease} onChange={(event) => setForceWithLease(event.target.checked)} className="accent-(--color-warning)" /> Force with lease</label>
          <span className="h-3 w-px bg-(--color-border)" />
          <span className="flex min-w-0 items-center gap-1.5">
            <UserRound size={10} />
            <span className="truncate">{userName && userEmail ? `${userName} <${userEmail}>` : 'Commit identity not configured'}</span>
          </span>
          <button type="button" onClick={() => setShowIdentity(!showIdentity)} className="rounded px-1.5 py-0.5 text-(--color-accent) hover:bg-(--bg-key)">Edit identity</button>
        </div>
        {showIdentity && (
          <div className="mt-2 grid grid-cols-2 gap-2 rounded-lg border border-(--color-border) bg-(--bg-card) p-2">
            <input value={identityName} onChange={(event) => setIdentityName(event.target.value)} placeholder="Git user name" className="h-8 min-w-0 rounded-md border border-(--color-border) bg-(--bg-base) px-2 text-[11px] text-(--color-text) outline-none focus:border-(--color-accent)" />
            <input value={identityEmail} onChange={(event) => setIdentityEmail(event.target.value)} placeholder="Git email" className="h-8 min-w-0 rounded-md border border-(--color-border) bg-(--bg-base) px-2 text-[11px] text-(--color-text) outline-none focus:border-(--color-accent)" />
            <div className="col-span-2 flex justify-end gap-1">
              <button type="button" onClick={() => setShowIdentity(false)} className="h-7 rounded-md px-2 text-[10px] text-(--color-text-muted) hover:bg-(--bg-key)">Cancel</button>
              <button
                type="button"
                disabled={!identityName.trim() || !identityEmail.trim() || identityMutation.isPending}
                onClick={() => identityMutation.mutate(
                  { name: identityName.trim(), email: identityEmail.trim() },
                  {
                    onSuccess: () => { setShowIdentity(false); useToastStore.getState().push({ tone: 'success', title: 'Git identity saved for this repository' }) },
                    onError: (error) => useToastStore.getState().push({ tone: 'error', title: 'Unable to save Git identity', description: error instanceof Error ? error.message : undefined }),
                  },
                )}
                className="h-7 rounded-md bg-(--color-accent) px-3 text-[10px] font-semibold text-(--color-text-on-accent) disabled:opacity-40"
              >
                Save identity
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-(--color-border) px-3">
        <RadioTower size={12} className="text-(--color-text-subtle)" />
        <span className="text-[11px] font-semibold text-(--color-text)">Configured remotes</span>
        <span className="rounded-full bg-(--bg-key) px-1.5 py-0.5 text-[9px] text-(--color-text-subtle)">{remotes.length}</span>
        <div className="flex-1" />
        <button
          type="button"
          onClick={() => { resetForm(); setShowForm(true) }}
          className="flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium text-(--color-accent) hover:bg-(--bg-key)"
        >
          <Plus size={11} /> Add remote
        </button>
      </div>

      {showForm && (
        <div className="grid shrink-0 grid-cols-[minmax(80px,0.35fr)_minmax(0,1fr)_auto] gap-2 border-b border-(--color-border) bg-(--bg-key)/20 p-3">
          <input
            value={name}
            disabled={Boolean(editingName)}
            onChange={(event) => setName(event.target.value)}
            placeholder="origin"
            className="h-8 rounded-md border border-(--color-border) bg-(--bg-base) px-2 text-[11px] text-(--color-text) outline-none focus:border-(--color-accent) disabled:opacity-60"
          />
          <input
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            onKeyDown={(event) => { if (event.key === 'Enter') submitRemote(); if (event.key === 'Escape') resetForm() }}
            placeholder="https://github.com/org/repository.git"
            className="h-8 min-w-0 rounded-md border border-(--color-border) bg-(--bg-base) px-2 font-mono text-[10px] text-(--color-text) outline-none focus:border-(--color-accent)"
            autoFocus
          />
          <div className="flex gap-1">
            <button type="button" onClick={resetForm} className="h-8 rounded-md px-2 text-[10px] text-(--color-text-muted) hover:bg-(--bg-key)">Cancel</button>
            <button type="button" onClick={submitRemote} disabled={busy || !name.trim() || !url.trim()} className="h-8 rounded-md bg-(--color-accent) px-3 text-[10px] font-semibold text-(--color-text-on-accent) disabled:opacity-40">{editingName ? 'Save' : 'Add'}</button>
          </div>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto divide-y divide-(--color-border)/40">
        {remotes.map((remote) => {
          const editRemote = () => {
            setEditingName(remote.name)
            setName(remote.name)
            setUrl(remote.fetch_url)
            setShowForm(true)
          }
          const removeRemote = () => deleteMutation.mutate(remote.name, {
            onSuccess: () => useToastStore.getState().push({ tone: 'info', title: `${remote.name} removed` }),
            onError: (error) => useToastStore.getState().push({ tone: 'error', title: 'Unable to remove remote', description: error instanceof Error ? error.message : undefined }),
          })
          const actions: GitAction[] = [
            { label: `Fetch ${remote.name}`, icon: <CloudDownload size={12} />, onSelect: () => startSync('fetch', () => fetchMutation.mutate({ remote: remote.name, prune })) },
            { label: `Pull from ${remote.name}`, icon: <RefreshCw size={12} />, onSelect: () => startSync('pull', () => pullMutation.mutate({ remote: remote.name, rebase })) },
            {
              label: `Push ${branch ?? 'current branch'} to ${remote.name}`,
              icon: <CloudUpload size={12} />,
              onSelect: () => startSync('push', () => pushMutation.mutate({
                remote: remote.name,
                branch: branch ?? undefined,
                setUpstream: !upstream,
                forceWithLease,
              })),
              disabled: !branch,
            },
            { label: 'Edit remote URL', icon: <Pencil size={12} />, onSelect: editRemote, separatorBefore: true },
            {
              label: 'Copy fetch URL',
              icon: <Copy size={12} />,
              onSelect: () => {
                void navigator.clipboard.writeText(remote.fetch_url)
                useToastStore.getState().push({ tone: 'info', title: 'Remote URL copied' })
              },
            },
            { label: 'Remove remote', icon: <Trash2 size={12} />, onSelect: removeRemote, danger: true, separatorBefore: true },
          ]
          return (
          <GitActionSurface key={remote.name} label={remote.name} actions={actions} className="flex items-center gap-3 px-3 py-2.5 hover:bg-(--bg-key)/50">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-(--bg-key) text-(--color-text-muted)"><RadioTower size={13} /></span>
            <div className="min-w-0 flex-1">
              <p className="text-[11px] font-semibold text-(--color-text)">{remote.name}</p>
              <p className="truncate font-mono text-[9px] text-(--color-text-subtle)" title={remote.fetch_url}>{remote.fetch_url}</p>
            </div>
          </GitActionSurface>
          )
        })}
        {remotes.length === 0 && (
          <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
            <RadioTower size={22} className="text-(--color-text-subtle)" />
            <p className="mt-2 text-xs font-medium text-(--color-text)">No remotes configured</p>
            <p className="mt-1 max-w-xs text-[11px] leading-5 text-(--color-text-muted)">Add a remote to fetch branches, push commits, and connect pull requests.</p>
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Tags Panel ──────────────────────────────────────────────────────────── */

function TagsPanel({ workspace }: { workspace: string }) {
  const tagsQuery = useGitTagsQuery(workspace)
  const remotesQuery = useGitRemotesQuery(workspace)
  const createMutation = useGitCreateTagMutation(workspace)
  const deleteMutation = useGitDeleteTagMutation(workspace)
  const pushMutation = useGitPushTagsMutation(workspace)
  const tags = tagsQuery.data ?? []
  const remotes = useMemo(() => remotesQuery.data ?? [], [remotesQuery.data])
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [target, setTarget] = useState('HEAD')
  const [message, setMessage] = useState('')
  const [remote, setRemote] = useState('origin')

  useEffect(() => {
    if (remotes.length > 0 && !remotes.some((item) => item.name === remote)) {
      setRemote(remotes[0].name) // eslint-disable-line react-hooks/set-state-in-effect -- synchronize remote selection with server data
    }
  }, [remote, remotes])

  const createTag = () => {
    if (!name.trim()) return
    createMutation.mutate(
      { name: name.trim(), target: target.trim() || 'HEAD', message: message.trim() || undefined },
      {
        onSuccess: () => {
          setName('')
          setTarget('HEAD')
          setMessage('')
          setShowCreate(false)
          useToastStore.getState().push({ tone: 'success', title: 'Tag created' })
        },
        onError: (error) => useToastStore.getState().push({ tone: 'error', title: 'Unable to create tag', description: error instanceof Error ? error.message : undefined }),
      },
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-(--color-border) px-3">
        <Tag size={12} className="text-(--color-text-subtle)" />
        <span className="text-[11px] font-semibold text-(--color-text)">Repository tags</span>
        <span className="rounded-full bg-(--bg-key) px-1.5 py-0.5 text-[9px] text-(--color-text-subtle)">{tags.length}</span>
        <div className="flex-1" />
        {remotes.length > 0 && (
          <>
            <SelectControl value={remote} onValueChange={setRemote} size="sm" ariaLabel="Remote for tags" className="min-w-24 bg-(--bg-card) text-[10px]" options={remotes.map((item) => ({ value: item.name, label: item.name }))} />
            <button
              type="button"
              disabled={pushMutation.isPending}
              onClick={() => pushMutation.mutate({ remote }, {
                onSuccess: () => useToastStore.getState().push({ tone: 'info', title: 'Tag push started' }),
                onError: (error) => useToastStore.getState().push({ tone: 'error', title: 'Unable to push tags', description: error instanceof Error ? error.message : undefined }),
              })}
              className="flex h-7 items-center gap-1 rounded-md border border-(--color-border) bg-(--bg-card) px-2 text-[10px] font-medium text-(--color-text-muted) hover:bg-(--bg-key)"
            >
              <CloudUpload size={11} /> Push tags
            </button>
          </>
        )}
        <button type="button" onClick={() => setShowCreate(!showCreate)} className="flex h-7 items-center gap-1 rounded-md px-2 text-[10px] font-medium text-(--color-accent) hover:bg-(--bg-key)"><Plus size={11} /> New tag</button>
      </div>

      {showCreate && (
        <div className="grid shrink-0 grid-cols-2 gap-2 border-b border-(--color-border) bg-(--bg-key)/20 p-3">
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="v1.0.0" className="h-8 rounded-md border border-(--color-border) bg-(--bg-base) px-2 font-mono text-[11px] text-(--color-text) outline-none focus:border-(--color-accent)" autoFocus />
          <input value={target} onChange={(event) => setTarget(event.target.value)} placeholder="HEAD or commit SHA" className="h-8 rounded-md border border-(--color-border) bg-(--bg-base) px-2 font-mono text-[11px] text-(--color-text) outline-none focus:border-(--color-accent)" />
          <input value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') createTag() }} placeholder="Annotation (optional)" className="col-span-2 h-8 rounded-md border border-(--color-border) bg-(--bg-base) px-2 text-[11px] text-(--color-text) outline-none focus:border-(--color-accent)" />
          <div className="col-span-2 flex justify-end gap-1">
            <button type="button" onClick={() => setShowCreate(false)} className="h-7 rounded-md px-2 text-[10px] text-(--color-text-muted) hover:bg-(--bg-key)">Cancel</button>
            <button type="button" onClick={createTag} disabled={!name.trim() || createMutation.isPending} className="h-7 rounded-md bg-(--color-accent) px-3 text-[10px] font-semibold text-(--color-text-on-accent) disabled:opacity-40">Create tag</button>
          </div>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto divide-y divide-(--color-border)/40">
        {tags.map((item) => {
          const deleteTag = () => deleteMutation.mutate(item.name, {
            onSuccess: () => useToastStore.getState().push({ tone: 'info', title: `${item.name} deleted locally` }),
            onError: (error) => useToastStore.getState().push({ tone: 'error', title: 'Unable to delete tag', description: error instanceof Error ? error.message : undefined }),
          })
          const actions: GitAction[] = [
            {
              label: 'Copy tag name',
              icon: <Copy size={12} />,
              onSelect: () => {
                void navigator.clipboard.writeText(item.name)
                useToastStore.getState().push({ tone: 'info', title: 'Tag name copied' })
              },
            },
            {
              label: 'Copy commit SHA',
              icon: <GitCommit size={12} />,
              onSelect: () => {
                void navigator.clipboard.writeText(item.sha)
                useToastStore.getState().push({ tone: 'info', title: 'Tag SHA copied' })
              },
            },
            {
              label: `Push tag to ${remote}`,
              icon: <CloudUpload size={12} />,
              onSelect: () => pushMutation.mutate(
                { remote, tag: item.name },
                {
                  onSuccess: () => useToastStore.getState().push({ tone: 'info', title: `Pushing ${item.name}` }),
                  onError: (error) => useToastStore.getState().push({ tone: 'error', title: 'Unable to push tag', description: error instanceof Error ? error.message : undefined }),
                },
              ),
              disabled: remotes.length === 0 || pushMutation.isPending,
              separatorBefore: true,
            },
            { label: 'Delete local tag', icon: <Trash2 size={12} />, onSelect: deleteTag, danger: true, separatorBefore: true },
          ]
          return (
          <GitActionSurface key={item.name} label={item.name} actions={actions} className="flex items-center gap-3 px-3 py-2.5 hover:bg-(--bg-key)/50">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-(--color-accent)/10 text-(--color-accent)"><Tag size={12} /></span>
            <div className="min-w-0 flex-1">
              <p className="truncate font-mono text-[11px] font-semibold text-(--color-text)">{item.name}</p>
              <p className="truncate text-[9px] text-(--color-text-subtle)">{item.sha} · {item.subject || 'Lightweight tag'}{item.date ? ` · ${formatDate(item.date)}` : ''}</p>
            </div>
          </GitActionSurface>
          )
        })}
        {tags.length === 0 && (
          <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
            <Tag size={22} className="text-(--color-text-subtle)" />
            <p className="mt-2 text-xs font-medium text-(--color-text)">No tags yet</p>
            <p className="mt-1 max-w-xs text-[11px] leading-5 text-(--color-text-muted)">Create lightweight or annotated tags at HEAD, a branch, or a commit.</p>
          </div>
        )}
      </div>
    </div>
  )
}
