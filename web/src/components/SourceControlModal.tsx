/**
 * Source Control Modal — IntelliJ-style unified layout.
 *
 * Layout (top → bottom):
 *   1. Toolbar: branch info + push/pull/fetch actions
 *   2. Commit area: message textarea + amend + commit buttons (always visible)
 *   3. Main split: file list (left) + unified diff viewer (right)
 *   4. Bottom rail: collapsible branches / history / stash panels
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
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
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { useToastStore } from '@/stores/useToastStore'
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
} from '@/queries/useGitQuery'
import type { CodingProject, ChangedFile } from '@/api/types'

/* ── Helpers ─────────────────────────────────────────────────────────────── */

function repoLabel(path: string): string {
  return path.split(/[\\/]/).pop() || path
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

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  modified: { label: 'M', cls: 'bg-amber-500/20 text-amber-400' },
  added: { label: 'A', cls: 'bg-green-500/20 text-green-400' },
  deleted: { label: 'D', cls: 'bg-red-500/20 text-red-400' },
  renamed: { label: 'R', cls: 'bg-blue-500/20 text-blue-400' },
  untracked: { label: '??', cls: 'bg-(--bg-key) text-(--color-text-muted)' },
  unmerged: { label: 'U', cls: 'bg-red-500/20 text-red-400' },
}

/**
 * Parse a unified diff string into structured hunks.
 * Each hunk has a header and an array of lines with their type.
 */
function parseUnifiedDiff(raw: string): DiffHunk[] {
  if (!raw) return []
  const hunks: DiffHunk[] = []
  let current: DiffHunk | null = null

  for (const line of raw.split('\n')) {
    if (line.startsWith('@@ ')) {
      // Hunk header: @@ -oldStart,oldCount +newStart,newCount @@
      const match = line.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$/)
      if (match) {
        current = {
          header: line,
          oldStart: parseInt(match[1], 10),
          newStart: parseInt(match[3], 10),
          lines: [],
        }
        hunks.push(current)
      }
    } else if (current) {
      if (line.startsWith('-')) {
        current.lines.push({ type: 'del', content: line.slice(1) })
      } else if (line.startsWith('+')) {
        current.lines.push({ type: 'add', content: line.slice(1) })
      } else if (line.startsWith(' ')) {
        current.lines.push({ type: 'ctx', content: line.slice(1) })
      } else if (line.startsWith('\\')) {
        // "\ No newline at end of file"
        current.lines.push({ type: 'info', content: line })
      }
    }
  }
  return hunks
}

interface DiffHunk {
  header: string
  oldStart: number
  newStart: number
  lines: DiffLine[]
}

interface DiffLine {
  type: 'add' | 'del' | 'ctx' | 'info'
  content: string
}

/* ── Types ───────────────────────────────────────────────────────────────── */

export interface SourceControlModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  workspace: string
  onWorkspaceChange?: (path: string) => void
  project?: CodingProject | null
  onFileOpenInEditor?: (path: string) => void
}

/* ── Main Modal ──────────────────────────────────────────────────────────── */

export function SourceControlModal({
  open,
  onOpenChange,
  workspace,
  onWorkspaceChange,
  project,
}: SourceControlModalProps) {
  const [showDiff, setShowDiff] = useState(true)
  const [selectedPath, setSelectedPath] = useState<string | null>(null)

  // Bottom panel — single active tab
  const [activePanel, setActivePanel] = useState<'branches' | 'history' | 'stash' | null>(null)
  const togglePanel = (p: 'branches' | 'history' | 'stash') => setActivePanel((prev) => (prev === p ? null : p))

  // Core queries
  const changesQuery = useGitChangesQuery(workspace, open)
  const conflictsQuery = useGitConflictsQuery(workspace, open)
  const branchesQuery = useGitBranchesQuery(workspace, open)
  const logQuery = useGitLogQuery(workspace, 0, undefined, open)
  const stashesQuery = useGitStashesQuery(workspace, open)
  const jobsQuery = useGitJobsQuery(workspace, open)

  const branch = changesQuery.data?.branch
  const ahead = changesQuery.data?.ahead ?? 0
  const behind = changesQuery.data?.behind ?? 0
  const files = changesQuery.data?.files ?? []
  const stagedFiles = files.filter((f) => f.staged)
  const unstagedFiles = files.filter((f) => !f.staged)
  const localBranches = (branchesQuery.data ?? []).filter((b) => !b.remote)
  const commits = logQuery.data?.entries ?? []
  const stashes = stashesQuery.data ?? []
  const runningJob = jobsQuery.data?.status === 'running' ? jobsQuery.data : null
  const siblingRepos = project?.workspaces.filter((w) => w.path !== workspace) ?? []

  // Conflict handling
  const conflicts = conflictsQuery.data
  const hasConflicts = conflicts?.conflicted ?? false
  const continueMutation = useGitContinueMutation(workspace)
  const abortMutation = useGitAbortMutation(workspace)

  // Fetch / Push / Pull
  const fetchMutation = useGitFetchMutation(workspace)
  const pushMutation = useGitPushMutation(workspace)
  const pullMutation = useGitPullMutation(workspace)

  // Auto-select first file
  useEffect(() => {
    if (open && !selectedPath && files.length > 0) {
      setSelectedPath(files[0].path)
    }
  }, [open, files, selectedPath])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        aria-labelledby="sc-title"
        className="flex !h-[88dvh] !max-h-[88dvh] !w-[88vw] !max-w-[88vw] flex-col gap-0 overflow-hidden !rounded-lg border-(--color-border) p-0"
      >
        {/* ═══ Toolbar ═══════════════════════════════════════════════════════ */}
        <div className="flex shrink-0 items-center gap-2 border-b border-(--color-border) bg-(--bg-key)/30 px-3 py-1.5">
          <h2 id="sc-title" className="text-xs font-semibold text-(--color-text)">Source Control</h2>
          <span className="text-[10px] text-(--color-text-subtle)">{repoLabel(workspace)}</span>
          {branch && (
            <span className="flex items-center gap-1 rounded bg-(--bg-key) px-2 py-0.5 text-[11px] font-medium text-(--color-text-muted)">
              <GitBranch size={11} /> {branch}
            </span>
          )}
          {ahead > 0 && <span className="text-[11px] font-medium text-green-400">↑{ahead}</span>}
          {behind > 0 && <span className="text-[11px] font-medium text-amber-400">↓{behind}</span>}
          {runningJob && (
            <span className="flex items-center gap-1 text-[11px] text-(--color-text-muted)">
              <Loader2 size={10} className="animate-spin" /> {runningJob.op}…
            </span>
          )}
          <div className="flex-1" />
          {siblingRepos.length > 0 && (
            <div className="flex items-center gap-0.5">
              {project!.workspaces.map((ws) => (
                <button
                  key={ws.path}
                  type="button"
                  onClick={() => onWorkspaceChange?.(ws.path)}
                  title={ws.display_name || ws.name || ws.path}
                  aria-label={ws.display_name || ws.name || 'Repository'}
                  className={cn(
                    'flex h-5 w-5 items-center justify-center rounded text-[9px] font-bold transition-colors',
                    ws.path === workspace ? 'bg-(--color-accent) text-white' : 'text-(--color-text-muted) hover:bg-(--bg-key)',
                  )}
                >
                  {(ws.display_name || ws.name || repoLabel(ws.path)).charAt(0).toUpperCase()}
                </button>
              ))}
            </div>
          )}
          <ToolbarButton icon={<RefreshCw size={13} />} label="Refresh" onClick={() => changesQuery.refetch()} />
          <div className="mx-0.5 h-4 w-px bg-(--color-border)" />
          <ToolbarButton
            icon={<CloudDownload size={13} />}
            label="Fetch"
            onClick={() => fetchMutation.mutate(undefined, {
              onSuccess: () => useToastStore.getState().push({ tone: 'success', title: 'Fetched' }),
              onError: () => useToastStore.getState().push({ tone: 'error', title: 'Fetch failed' }),
            })}
          />
          <ToolbarButton
            icon={<CloudUpload size={13} />}
            label="Push"
            onClick={() => pushMutation.mutate(undefined, {
              onSuccess: () => useToastStore.getState().push({ tone: 'success', title: 'Pushed' }),
              onError: () => useToastStore.getState().push({ tone: 'error', title: 'Push failed' }),
            })}
            badge={ahead > 0 ? String(ahead) : undefined}
          />
          <ToolbarButton
            icon={<RefreshCw size={13} />}
            label="Pull"
            onClick={() => pullMutation.mutate(undefined, {
              onSuccess: () => useToastStore.getState().push({ tone: 'success', title: 'Pulled' }),
              onError: () => useToastStore.getState().push({ tone: 'error', title: 'Pull failed' }),
            })}
            badge={behind > 0 ? String(behind) : undefined}
          />
          <div className="mx-0.5 h-4 w-px bg-(--color-border)" />
          <button type="button" onClick={() => onOpenChange(false)} className="flex h-6 w-6 items-center justify-center rounded text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)" aria-label="Close">
            <X size={14} />
          </button>
        </div>

        {/* ═══ Conflict Banner ═════════════════════════════════════════════ */}
        {hasConflicts && (
          <ConflictBar
            conflicts={conflicts!}
            onContinue={() => continueMutation.mutate(undefined, { onSuccess: () => useToastStore.getState().push({ tone: 'success', title: 'Continued' }), onError: () => useToastStore.getState().push({ tone: 'error', title: 'Failed' }) })}
            onAbort={() => abortMutation.mutate(undefined, { onSuccess: () => useToastStore.getState().push({ tone: 'info', title: 'Aborted' }), onError: () => useToastStore.getState().push({ tone: 'error', title: 'Failed' }) })}
          />
        )}

        {/* ═══ Body: Left Rail + Side Panel + Main Content ══════════════ */}
        <div className="flex min-h-0 flex-1 overflow-hidden">

          {/* Left icon rail (Activity Bar) */}
          <div className="flex w-10 shrink-0 flex-col items-center gap-0.5 border-r border-(--color-border) bg-(--bg-key)/30 py-2">
            <SideTab icon={<GitBranch size={15} />} label="Branches" count={localBranches.length} active={activePanel === 'branches'} onClick={() => togglePanel('branches')} />
            <SideTab icon={<History size={15} />} label="History" count={commits.length} active={activePanel === 'history'} onClick={() => togglePanel('history')} />
            <SideTab icon={<Archive size={15} />} label="Stash" count={stashes.length} active={activePanel === 'stash'} onClick={() => togglePanel('stash')} />
            <div className="flex-1" />
            <button
              type="button"
              onClick={() => setShowDiff(!showDiff)}
              className={cn(
                'flex h-8 w-8 items-center justify-center rounded transition-colors',
                showDiff ? 'text-(--color-accent)' : 'text-(--color-text-muted) hover:text-(--color-text)',
              )}
              title={showDiff ? 'Hide diff' : 'Show diff'}
              aria-label={showDiff ? 'Hide diff' : 'Show diff'}
            >
              {showDiff ? <PanelRightClose size={15} /> : <PanelRightOpen size={15} />}
            </button>
          </div>

          {/* Side panel (collapsible) */}
          {activePanel && (
            <div className="w-64 shrink-0 overflow-hidden border-r border-(--color-border)">
              {activePanel === 'branches' && <BranchesPanel workspace={workspace} />}
              {activePanel === 'history' && <HistoryPanel workspace={workspace} />}
              {activePanel === 'stash' && <StashPanel workspace={workspace} />}
            </div>
          )}

          {/* Main content: File list + Diff */}
          <div className="flex min-w-0 flex-1 overflow-hidden">
            <FileListPanel
              workspace={workspace}
              stagedFiles={stagedFiles}
              unstagedFiles={unstagedFiles}
              isLoading={changesQuery.isLoading}
              selectedPath={selectedPath}
              onSelect={setSelectedPath}
            />
            {showDiff && <DiffPanel workspace={workspace} path={selectedPath} />}
          </div>
        </div>

        {/* ═══ Commit Area (bottom) ═══════════════════════════════════════ */}
        <CommitArea workspace={workspace} stagedCount={stagedFiles.length} />
      </DialogContent>
    </Dialog>
  )
}

/* ── Toolbar Button ──────────────────────────────────────────────────────── */

function ToolbarButton({ icon, label, onClick, badge }: { icon: React.ReactNode; label: string; onClick: () => void; badge?: string }) {
  return (
    <button type="button" onClick={onClick} title={label} aria-label={label} className="relative flex h-6 items-center gap-1 rounded px-1.5 text-[11px] text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)">
      {icon}
      {badge && <span className="absolute -right-1 -top-1 flex h-3.5 min-w-[14px] items-center justify-center rounded-full bg-(--color-accent) px-0.5 text-[8px] font-bold text-white">{badge}</span>}
    </button>
  )
}

/* ── Conflict Banner ─────────────────────────────────────────────────────── */

function ConflictBar({ conflicts, onContinue, onAbort }: { conflicts: { operation: string | null; files: { path: string; status: string }[] }; onContinue: () => void; onAbort: () => void }) {
  return (
    <div className="flex items-center gap-3 border-b border-red-500/30 bg-red-500/10 px-3 py-1.5">
      <span className="text-[11px] font-medium text-red-300">
        {conflicts.operation ? `${conflicts.operation} conflict` : 'Conflicts'} — {conflicts.files.length} file{conflicts.files.length !== 1 ? 's' : ''}
      </span>
      <div className="flex-1" />
      <button type="button" onClick={onContinue} className="rounded bg-green-600 px-2 py-0.5 text-[11px] font-medium text-white hover:bg-green-500">Continue</button>
      <button type="button" onClick={onAbort} className="rounded px-2 py-0.5 text-[11px] text-red-300 hover:bg-red-500/20">Abort</button>
    </div>
  )
}

/* ── Commit Area — bottom bar style ─────────────────────────────────────── */

function CommitArea({ workspace, stagedCount }: { workspace: string; stagedCount: number }) {
  const [message, setMessage] = useState('')
  const [amend, setAmend] = useState(false)
  const commitMutation = useGitCommitMutation(workspace)

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

  return (
    <div className="flex shrink-0 items-stretch gap-3 border-t border-(--color-border) bg-(--bg-key)/30 px-3 py-2">
      {/* Message input */}
      <textarea
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleCommit() }}
        placeholder="Commit message…  ⌘+Enter"
        rows={2}
        className="min-w-0 flex-1 resize-none rounded border border-(--color-border) bg-(--bg-base) px-2.5 py-1.5 text-xs text-(--color-text) outline-none placeholder:text-(--color-text-subtle) focus:border-(--color-accent)"
      />

      {/* Right: staged info + amend + commit button */}
      <div className="flex w-40 shrink-0 flex-col items-end justify-between">
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-[10px] text-(--color-text-muted)">
            <input type="checkbox" checked={amend} onChange={() => setAmend(!amend)} className="h-3 w-3 accent-(--color-accent)" />
            Amend
          </label>
          <span className={cn(
            'rounded px-1.5 py-0.5 text-[9px] font-medium',
            stagedCount > 0 ? 'bg-(--color-accent)/20 text-(--color-accent)' : 'bg-(--bg-key) text-(--color-text-subtle)',
          )}>
            {stagedCount} staged
          </span>
        </div>
        <button
          type="button"
          onClick={handleCommit}
          disabled={commitMutation.isPending || (!message.trim() && !amend) || stagedCount === 0}
          className={cn(
            'flex items-center gap-1.5 rounded px-4 py-1.5 text-[11px] font-medium transition-colors',
            'bg-(--color-accent) text-white hover:bg-(--color-accent)/90 disabled:opacity-40',
          )}
        >
          {commitMutation.isPending ? <Loader2 size={11} className="animate-spin" /> : <GitCommit size={11} />}
          Commit
        </button>
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

  if (isLoading) return <div className="flex w-72 shrink-0 items-center justify-center border-r border-(--color-border)"><Loader2 size={14} className="animate-spin text-(--color-text-subtle)" /></div>

  return (
    <div className="flex w-72 shrink-0 flex-col border-r border-(--color-border)">
      <div className="flex items-center gap-1.5 border-b border-(--color-border) px-2 py-1">
        <Search size={12} className="shrink-0 text-(--color-text-subtle)" />
        <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter files…" className="flex-1 bg-transparent text-[11px] text-(--color-text) outline-none placeholder:text-(--color-text-subtle)" />
        {filter && <button type="button" onClick={() => setFilter('')} className="text-(--color-text-subtle) hover:text-(--color-text)"><X size={10} /></button>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {filteredStaged.length > 0 && (
          <div>
            <div className="flex items-center justify-between px-2 py-1">
              <span className="text-[10px] font-medium uppercase tracking-wide text-(--color-text-subtle)">Staged ({filteredStaged.length})</span>
              <button type="button" onClick={() => unstageMutation.mutate(filteredStaged.map((f) => f.path))} className="text-[10px] text-(--color-text-muted) hover:text-(--color-text)" title="Unstage all" aria-label="Unstage all"><RotateCcw size={11} /></button>
            </div>
            {filteredStaged.map((file) => <FileRow key={file.path} file={file} selected={selectedPath === file.path} onSelect={() => onSelect(file.path)} onToggleStage={() => unstageMutation.mutate([file.path])} />)}
          </div>
        )}
        {filteredUnstaged.length > 0 && (
          <div>
            <div className="flex items-center justify-between px-2 py-1">
              <span className="text-[10px] font-medium uppercase tracking-wide text-(--color-text-subtle)">Changes ({filteredUnstaged.length})</span>
              <button type="button" onClick={() => stageMutation.mutate(filteredUnstaged.map((f) => f.path))} className="text-[10px] text-(--color-text-muted) hover:text-(--color-text)" title="Stage all" aria-label="Stage all"><Plus size={11} /></button>
            </div>
            {filteredUnstaged.map((file) => <FileRow key={file.path} file={file} selected={selectedPath === file.path} onSelect={() => onSelect(file.path)} onToggleStage={() => stageMutation.mutate([file.path])} onDiscard={file.status !== 'untracked' ? () => discardMutation.mutate([file.path]) : undefined} />)}
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
  return (
    <div
      className={cn('group flex items-center gap-1 px-2 py-[3px] text-left cursor-pointer', selected ? 'bg-(--color-accent)/10 border-l-2 border-(--color-accent)' : 'border-l-2 border-transparent hover:bg-(--bg-key)')}
      onClick={onSelect}
    >
      <button type="button" onClick={(e) => { e.stopPropagation(); onToggleStage() }} className={cn('flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors', file.staged ? 'border-(--color-accent) bg-(--color-accent) text-white' : 'border-(--color-border) hover:border-(--color-accent)')} aria-label={file.staged ? 'Unstage' : 'Stage'}>
        {file.staged && <Check size={10} />}
      </button>
      <span className={cn('flex h-4 w-4 shrink-0 items-center justify-center rounded text-[9px] font-bold', badge.cls)}>{badge.label}</span>
      <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-(--color-text)">
        {file.old_path ? <span title={`${file.old_path} → ${file.path}`}>{file.path.split('/').pop()}<span className="text-(--color-text-subtle)"> ← {file.old_path?.split('/').pop()}</span></span> : file.path}
      </span>
      {onDiscard && <button type="button" onClick={(e) => { e.stopPropagation(); onDiscard() }} className="hidden shrink-0 rounded p-0.5 text-(--color-text-muted) hover:text-(--color-error) group-hover:flex" title="Discard" aria-label="Discard changes"><RotateCcw size={10} /></button>}
    </div>
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
      <span className="w-10 shrink-0 select-none border-r border-(--color-border)/30 px-1 text-right text-[9px] text-(--color-text-subtle)/60">
        {oldNum ?? ''}
      </span>
      {/* New line number */}
      <span className="w-10 shrink-0 select-none border-r border-(--color-border)/30 px-1 text-right text-[9px] text-(--color-text-subtle)/60">
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

/* ── Side Tab — VS Code Activity Bar style ─────────────────────────────── */

function SideTab({ icon, label, count, active, onClick }: {
  icon: React.ReactNode; label: string; count: number; active: boolean; onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className={cn(
        'relative flex h-8 w-8 items-center justify-center rounded transition-colors',
        active
          ? 'text-(--color-text)'
          : 'text-(--color-text-muted) hover:text-(--color-text)',
      )}
    >
      {icon}
      {/* Badge */}
      {count > 0 && (
        <span className={cn(
          'absolute -right-0.5 -top-0.5 flex h-3.5 min-w-[14px] items-center justify-center rounded-full px-0.5 text-[8px] font-bold',
          active ? 'bg-(--color-accent) text-white' : 'bg-(--bg-key) text-(--color-text-subtle)',
        )}>
          {count}
        </span>
      )}
      {/* Active indicator bar on left edge */}
      {active && <div className="absolute left-0 top-1 bottom-1 w-0.5 rounded-full bg-(--color-accent)" />}
    </button>
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
            <button type="button" onClick={() => { if (newBranch.trim()) createBranchMutation.mutate(newBranch.trim(), { onSuccess: () => { setNewBranch(''); setShowCreate(false) } }) }} disabled={busy || !newBranch.trim()} className="rounded bg-(--color-accent) px-2 py-0.5 text-[10px] font-medium text-white disabled:opacity-50">Create</button>
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
      </div>
    </div>
  )
}

function BranchRow({ branch, busy, onCheckout, onDelete, onMerge, onRebase }: {
  branch: { name: string; current: boolean; ahead: number; behind: number }
  busy: boolean; onCheckout: () => void; onDelete: () => void; onMerge: () => void; onRebase: () => void
}) {
  const [hovered, setHovered] = useState(false)
  return (
    <div
      className={cn('group flex items-center gap-2 px-3 py-1.5 transition-colors', branch.current ? 'bg-(--color-accent)/5' : 'hover:bg-(--bg-key)')}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Branch indicator */}
      <div className={cn('h-3 w-3 shrink-0 rounded-full border-2', branch.current ? 'border-green-400 bg-green-400/30' : 'border-(--color-text-subtle)/40 bg-transparent')} />

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

      {/* Actions */}
      {!branch.current && (
        <div className={cn('flex shrink-0 items-center gap-0.5 transition-opacity', hovered ? 'opacity-100' : 'opacity-0')}>
          <ActionBtn icon={<ArrowRightLeft size={10} />} label="Checkout" onClick={onCheckout} disabled={busy} />
          <ActionBtn icon={<GitMerge size={10} />} label="Merge" onClick={onMerge} disabled={busy} />
          <ActionBtn icon={<span className="text-[8px] font-bold">RB</span>} label="Rebase" onClick={onRebase} disabled={busy} />
          <div className="mx-0.5 h-3 w-px bg-(--color-border)" />
          <ActionBtn icon={<Trash2 size={10} />} label="Delete" onClick={onDelete} disabled={busy} danger />
        </div>
      )}
    </div>
  )
}

function ActionBtn({ icon, label, onClick, disabled, danger }: {
  icon: React.ReactNode; label: string; onClick: () => void; disabled?: boolean; danger?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className={cn(
        'rounded px-1.5 py-0.5 text-[9px] transition-colors disabled:opacity-30',
        danger
          ? 'text-(--color-text-muted) hover:bg-red-500/10 hover:text-red-400'
          : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
      )}
    >
      {icon}
    </button>
  )
}

/* ── History Panel — Git Graph / SourceTree style ──────────────────────── */

// Branch lane colors — each lane gets a distinct color
const LANE_COLORS = [
  { line: 'bg-blue-500', node: 'border-blue-500 bg-blue-500', dot: 'bg-blue-500' },
  { line: 'bg-green-500', node: 'border-green-500 bg-green-500', dot: 'bg-green-500' },
  { line: 'bg-purple-500', node: 'border-purple-500 bg-purple-500', dot: 'bg-purple-500' },
  { line: 'bg-amber-500', node: 'border-amber-500 bg-amber-500', dot: 'bg-amber-500' },
  { line: 'bg-pink-500', node: 'border-pink-500 bg-pink-500', dot: 'bg-pink-500' },
  { line: 'bg-cyan-500', node: 'border-cyan-500 bg-cyan-500', dot: 'bg-cyan-500' },
]

const GRAPH_W = 52 // width of graph column
const NODE_X = 20 // x position of main node center
const NODE_R = 5  // node radius
const LINE_W = 2  // line width

function HistoryPanel({ workspace }: { workspace: string }) {
  const [page, setPage] = useState(0)
  const [expandedSha, setExpandedSha] = useState<string | null>(null)
  const logQuery = useGitLogQuery(workspace, page)
  const logFilesQuery = useGitLogFilesQuery(workspace, expandedSha, !!expandedSha)
  const cherryPickMutation = useGitCherryPickMutation(workspace)
  const entries = logQuery.data?.entries ?? []
  const hasMore = logQuery.data?.has_more ?? false

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {/* Toolbar */}
      <div className="flex shrink-0 items-center justify-between border-b border-(--color-border) px-3 py-1.5">
        <div className="flex items-center gap-1.5">
          <History size={12} className="text-(--color-text-subtle)" />
          <span className="text-[11px] font-medium text-(--color-text)">History</span>
        </div>
        <div className="flex items-center gap-1">
          <button type="button" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0} className="rounded px-2 py-0.5 text-[10px] text-(--color-text-muted) hover:bg-(--bg-key) disabled:opacity-40">← Newer</button>
          <span className="min-w-[30px] text-center text-[10px] text-(--color-text-subtle)">p{page + 1}</span>
          <button type="button" onClick={() => setPage((p) => p + 1)} disabled={!hasMore} className="rounded px-2 py-0.5 text-[10px] text-(--color-text-muted) hover:bg-(--bg-key) disabled:opacity-40">Older →</button>
        </div>
      </div>

      {/* Graph + Commit list */}
      {logQuery.isLoading ? (
        <div className="flex items-center justify-center py-8"><Loader2 size={14} className="animate-spin text-(--color-text-subtle)" /></div>
      ) : entries.length === 0 ? (
        <div className="flex items-center justify-center py-8 text-[11px] text-(--color-text-subtle)">No commits</div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto">
          {entries.map((entry, idx) => (
            <CommitRow
              key={entry.sha}
              entry={entry}
              idx={idx}
              isHead={idx === 0 && page === 0}
              isExpanded={expandedSha === entry.sha}
              isLast={idx === entries.length - 1}
              total={entries.length}
              onToggle={() => setExpandedSha(expandedSha === entry.sha ? null : entry.sha)}
              onCherryPick={() => cherryPickMutation.mutate([entry.sha], {
                onSuccess: (data) => {
                  if (data.success) useToastStore.getState().push({ tone: 'success', title: 'Cherry-picked' })
                  else useToastStore.getState().push({ tone: 'error', title: 'Conflicts', description: data.conflicts.join(', ') })
                },
              })}
              filesQuery={logFilesQuery}
              isFilesLoading={logFilesQuery.isLoading && expandedSha === entry.sha}
              files={expandedSha === entry.sha ? (logFilesQuery.data ?? []) : []}
            />
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Single Commit Row with Graph ────────────────────────────────────────── */

function CommitRow({
  entry, idx, isHead, isExpanded, isLast,
  onToggle, onCherryPick, isFilesLoading, files,
}: {
  entry: { sha: string; short_sha: string; author: string; date: string; message: string }
  idx: number; isHead: boolean; isExpanded: boolean; isLast: boolean; total: number
  onToggle: () => void; onCherryPick: () => void
  filesQuery: ReturnType<typeof useGitLogFilesQuery>
  isFilesLoading: boolean
  files: { path: string; status: string }[]
}) {
  const isMerge = entry.message.toLowerCase().startsWith('merge')
  const color = isMerge ? LANE_COLORS[1] : LANE_COLORS[0]
  const ROW_H = 36 // row height in px

  return (
    <div>
      {/* ── Commit Row ── */}
      <div
        className={cn(
          'group flex cursor-pointer transition-colors',
          isExpanded ? 'bg-(--bg-key)' : 'hover:bg-(--bg-key)/50',
        )}
        style={{ height: ROW_H }}
        onClick={onToggle}
      >
        {/* ── Graph Column ── */}
        <div className="relative shrink-0" style={{ width: GRAPH_W }}>
          {/* Vertical line: top half */}
          {idx > 0 && (
            <div
              className={cn('absolute top-0', color.line)}
              style={{ left: NODE_X - LINE_W / 2, width: LINE_W, height: ROW_H / 2 }}
            />
          )}
          {/* Vertical line: bottom half */}
          {!isLast && (
            <div
              className={cn('absolute', color.line)}
              style={{ left: NODE_X - LINE_W / 2, width: LINE_W, top: ROW_H / 2, height: ROW_H / 2 }}
            />
          )}

          {/* Merge: horizontal branch connector */}
          {isMerge && (
            <>
              {/* Horizontal line from main to branch */}
              <div
                className="absolute bg-green-500"
                style={{ left: NODE_X + NODE_R + 2, top: ROW_H / 2 - LINE_W / 2, width: 14, height: LINE_W }}
              />
              {/* Vertical branch line */}
              <div
                className="absolute bg-green-500"
                style={{ left: NODE_X + NODE_R + 14 - LINE_W / 2, top: ROW_H / 2 - 10, width: LINE_W, height: 20 }}
              />
              {/* Small dot at branch end */}
              <div
                className="absolute rounded-full bg-green-500"
                style={{ left: NODE_X + NODE_R + 14 - 3, top: ROW_H / 2 - 3, width: 6, height: 6 }}
              />
            </>
          )}

          {/* ── Commit Node ── */}
          <div
            className="absolute flex items-center justify-center"
            style={{ left: NODE_X - NODE_R, top: ROW_H / 2 - NODE_R, width: NODE_R * 2, height: NODE_R * 2 }}
          >
            {isHead ? (
              // HEAD: filled accent node with ring
              <div className="relative flex items-center justify-center">
                <div className="h-[14px] w-[14px] rounded-full bg-(--color-accent) shadow-[0_0_0_3px] shadow-(--bg-base)" />
                <div className="absolute h-[6px] w-[6px] rounded-full bg-white" />
              </div>
            ) : isMerge ? (
              // Merge: larger node with inner dot
              <div className="relative flex items-center justify-center">
                <div className={cn('h-[12px] w-[12px] rounded-full border-2', color.node)} />
                <div className="absolute h-[4px] w-[4px] rounded-full bg-white" />
              </div>
            ) : (
              // Normal: small filled dot
              <div className={cn('h-[8px] w-[8px] rounded-full', color.dot)} />
            )}
          </div>
        </div>

        {/* ── Commit Info ── */}
        <div className="min-w-0 flex-1 border-l border-transparent px-2 py-1">
          <div className="flex items-center gap-1.5">
            <p className="min-w-0 flex-1 truncate text-[11px] font-medium text-(--color-text) leading-tight">
              {entry.message}
            </p>
            {isHead && (
              <span className="shrink-0 rounded bg-(--color-accent)/20 px-1.5 py-0.5 text-[8px] font-bold text-(--color-accent) leading-none">HEAD</span>
            )}
            {isMerge && (
              <span className="shrink-0 rounded bg-green-500/20 px-1.5 py-0.5 text-[8px] font-medium text-green-400 leading-none">merge</span>
            )}
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[9px] text-(--color-text-subtle)">
            <span
              className="cursor-pointer rounded bg-(--bg-key) px-1 py-0.5 font-mono text-[8px] text-(--color-accent) hover:bg-(--color-accent)/20 transition-colors"
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
            <span>{formatDate(entry.date)}</span>
          </div>
        </div>

        {/* ── Actions (hover) ── */}
        <div className="flex shrink-0 items-center gap-0.5 pr-2 opacity-0 transition-opacity group-hover:opacity-100">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              void navigator.clipboard.writeText(entry.sha)
              useToastStore.getState().push({ tone: 'info', title: 'SHA copied' })
            }}
            className="rounded p-1 text-[9px] text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
            title="Copy SHA"
            aria-label="Copy SHA"
          >
            <Copy size={10} />
          </button>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onCherryPick() }}
            className="rounded p-1 text-[9px] text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
            title="Cherry-pick"
            aria-label="Cherry-pick commit"
          >
            <GitCommit size={10} />
          </button>
        </div>
      </div>

      {/* ── Expanded: files changed ── */}
      {isExpanded && (
        <div className="flex">
          {/* Spacer for graph column */}
          <div className="shrink-0" style={{ width: GRAPH_W }} />
          {/* Files list */}
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
            <button type="button" onClick={() => createMutation.mutate({ message: message.trim() || undefined }, { onSuccess: () => { setMessage(''); setShowCreate(false) } })} disabled={createMutation.isPending} className="rounded bg-(--color-accent) px-2 py-0.5 text-[10px] font-medium text-white disabled:opacity-50">Stash</button>
          </div>
        )}

        {/* Stash list */}
        <div className="divide-y divide-(--color-border)/30">
          {stashes.map((stash) => (
            <div key={stash.index} className="group flex items-center gap-2 px-3 py-1.5 hover:bg-(--bg-key)">
              <Archive size={11} className="shrink-0 text-(--color-text-subtle)" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[11px] text-(--color-text)">{stash.message}</p>
                <p className="font-mono text-[9px] text-(--color-text-subtle)">{stash.sha}</p>
              </div>
              <div className="flex shrink-0 items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                <ActionBtn icon={<Play size={10} />} label="Apply stash" onClick={() => applyMutation.mutate(stash.index)} disabled={busy} />
                <ActionBtn icon={<ArrowUpFromLine size={10} />} label="Pop stash" onClick={() => popMutation.mutate(stash.index)} disabled={busy} />
                <div className="mx-0.5 h-3 w-px bg-(--color-border)" />
                <ActionBtn icon={<Trash2 size={10} />} label="Drop stash" onClick={() => dropMutation.mutate(stash.index)} disabled={busy} danger />
              </div>
            </div>
          ))}
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
