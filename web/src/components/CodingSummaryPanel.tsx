import { useEffect, useMemo } from 'react'
import {
  ArrowUpRight,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  CircleAlert,
  FileDiff,
  Files,
  GitBranch,
  GitCommitHorizontal,
  GitPullRequest,
  Globe2,
  LayoutDashboard,
  Loader2,
  RefreshCw,
  Terminal,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import type { ChangedFile, TurnChangedFile } from '@/api/types'
import { cn } from '@/lib/utils'
import { useGitChangesQuery } from '@/queries/useGitQuery'
import { useTodosQuery } from '@/queries/useTodosQuery'
import { useTeamStore } from '@/stores/useTeamStore'
import { useUIStore, type WorkbenchTool } from '@/stores/useUIStore'
import { workspaceLabel } from '@/utils/workspace'

interface CodingSummaryPanelProps {
  workspace: string
  sessionId: string | null
  open: boolean
  isWorking: boolean
  onOpenFile?: (path: string) => void
}

interface SummaryRowProps {
  icon: LucideIcon
  label: string
  detail?: string
  trailing?: React.ReactNode
  onClick?: () => void
  disabled?: boolean
}

function SummaryRow({
  icon: Icon,
  label,
  detail,
  trailing,
  onClick,
  disabled = false,
}: SummaryRowProps) {
  const content = (
    <>
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-(--bg-key) text-(--color-text-muted)">
        <Icon size={14} aria-hidden="true" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs font-medium text-(--color-text)">
          {label}
        </span>
        {detail && (
          <span className="mt-0.5 block truncate text-[11px] leading-4 text-(--color-text-subtle)">
            {detail}
          </span>
        )}
      </span>
      {trailing}
      {onClick && !disabled && (
        <ChevronRight
          size={13}
          className="shrink-0 text-(--color-text-subtle) transition-transform group-hover:translate-x-0.5"
          aria-hidden="true"
        />
      )}
    </>
  )

  if (!onClick) {
    return <div className="flex min-h-11 items-center gap-2.5 px-3 py-2">{content}</div>
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="group flex min-h-11 w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-(--bg-key)/65 disabled:cursor-default disabled:opacity-55 disabled:hover:bg-transparent"
    >
      {content}
    </button>
  )
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section>
      <h3 className="mb-1.5 px-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-(--color-text-subtle)">
        {title}
      </h3>
      <div className="divide-y divide-(--color-border-subtle) overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-card)/65 shadow-sm">
        {children}
      </div>
    </section>
  )
}

function recentPath(file: TurnChangedFile | ChangedFile): string {
  return file.path
}

export function CodingSummaryPanel({
  workspace,
  sessionId,
  open,
  isWorking,
  onOpenFile,
}: CodingSummaryPanelProps) {
  const gitChanges = useGitChangesQuery(workspace, open)
  const {
    data: gitData,
    isFetching: gitIsFetching,
    isLoading: gitIsLoading,
    refetch: refetchGitChanges,
  } = gitChanges
  const todosQuery = useTodosQuery(sessionId)
  const turnChanges = useTeamStore((state) => state.turnChanges)
  const openWorkbenchTool = useUIStore((state) => state.openWorkbenchTool)
  const currentTurnChanges =
    turnChanges?.sessionId === sessionId ? turnChanges : null

  // `turn_changes` arrives once the agent finishes mutating files. Refresh the
  // repository snapshot at that boundary so the overview does not require a
  // manual refresh to reflect the completed turn.
  useEffect(() => {
    if (!open || !currentTurnChanges) return
    void refetchGitChanges()
  }, [currentTurnChanges, open, refetchGitChanges])

  const files = useMemo(() => gitData?.files ?? [], [gitData?.files])
  const stagedCount = files.filter((file) => file.staged).length
  const untrackedCount = files.filter((file) => file.status === 'untracked').length
  const todos = todosQuery.data?.todos ?? []
  const completedTodos = todos.filter(
    (todo) => todo.status === 'completed' || todo.status === 'cancelled',
  ).length
  const activeTodo = todos.find((todo) => todo.status === 'in_progress')
  const progressDetail = activeTodo?.content
    ?? (todos.length > 0
      ? `${completedTodos} of ${todos.length} tasks complete`
      : sessionId
        ? 'No progress milestones yet'
        : 'Start a session to track progress')
  const recentFiles = useMemo(
    () => (currentTurnChanges?.files.length
      ? currentTurnChanges.files
      : files).slice(0, 6),
    [currentTurnChanges?.files, files],
  )
  const branch = gitData?.branch
  const repositoryDetail = gitIsLoading
    ? 'Reading repository state…'
    : !gitData?.is_git_repo
      ? 'Not a Git repository'
      : files.length === 0
        ? 'Working tree clean'
        : `${files.length} changed ${files.length === 1 ? 'file' : 'files'}`
  const syncDetail = gitData
    ? gitData.ahead > 0 || gitData.behind > 0
      ? `${gitData.ahead} ahead · ${gitData.behind} behind`
      : stagedCount > 0
        ? `${stagedCount} staged`
        : untrackedCount > 0
          ? `${untrackedCount} untracked`
          : 'Review, commit, and sync changes'
    : 'Review, commit, and sync changes'

  const openTool = (tool: WorkbenchTool) => () => openWorkbenchTool(tool)
  const refresh = () => {
    void Promise.all([
      refetchGitChanges(),
      todosQuery.refetch(),
    ])
  }
  const refreshing =
    gitIsFetching || todosQuery.isFetching

  return (
    <div className="flex h-full min-h-0 flex-col bg-(--bg-page)">
      <header className="flex shrink-0 items-center gap-3 border-b border-(--color-border) bg-(--bg-card)/35 px-4 py-3">
        <span className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-(--color-border) bg-(--bg-card) text-(--color-accent) shadow-sm">
          <LayoutDashboard size={17} aria-hidden="true" />
          {isWorking && (
            <span
              className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 animate-pulse rounded-full border-2 border-(--bg-card) bg-(--color-success)"
              aria-label="Agent is working"
            />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold text-(--color-text)">
            {workspaceLabel(workspace)}
          </span>
          <span className="block truncate font-mono text-[10px] text-(--color-text-subtle)" title={workspace}>
            {workspace}
          </span>
        </span>
        <button
          type="button"
          onClick={refresh}
          disabled={refreshing}
          className="focus-ring-control flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-50"
          aria-label="Refresh summary"
          title="Refresh summary"
        >
          <RefreshCw size={14} className={cn(refreshing && 'animate-spin')} />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-4">
        <div className="mx-auto w-full max-w-2xl space-y-5">
          <Section title="Environment">
            <SummaryRow
              icon={FileDiff}
              label="Changes"
              detail={repositoryDetail}
              onClick={openTool('source-control')}
              trailing={currentTurnChanges && (
                <span
                  className="shrink-0 font-mono text-[10px] tabular-nums"
                  title="Changes from the latest agent turn"
                >
                  <span className="text-(--color-success)">+{currentTurnChanges.additions}</span>
                  {' '}
                  <span className="text-(--color-error)">−{currentTurnChanges.deletions}</span>
                </span>
              )}
            />
            <SummaryRow
              icon={CircleAlert}
              label="Problems"
              detail="LSP, build, test, AI, security, and plugin findings"
              onClick={openTool('problems')}
            />
            <SummaryRow
              icon={Files}
              label="Local workspace"
              detail={workspaceLabel(workspace)}
              onClick={openTool('files')}
            />
            <SummaryRow
              icon={GitBranch}
              label={branch ?? 'No branch'}
              detail={
                gitData?.is_git_repo
                  ? 'Current branch'
                  : 'Repository information unavailable'
              }
            />
            <SummaryRow
              icon={GitCommitHorizontal}
              label="Commit or push"
              detail={syncDetail}
              onClick={openTool('source-control')}
              disabled={!gitData?.is_git_repo}
            />
            <SummaryRow
              icon={GitPullRequest}
              label="Review pull requests"
              detail="Open repository review work"
              onClick={openTool('pull-requests')}
            />
          </Section>

          <Section title="Session">
            <SummaryRow
              icon={isWorking ? Loader2 : CheckCircle2}
              label={isWorking ? 'Agent working' : 'Tasks'}
              detail={progressDetail}
              trailing={
                todos.length > 0 ? (
                  <span className="shrink-0 font-mono text-[10px] tabular-nums text-(--color-text-muted)">
                    {completedTodos}/{todos.length}
                  </span>
                ) : undefined
              }
            />
            <SummaryRow
              icon={Globe2}
              label="Browser"
              detail="Open the session browser"
              onClick={openTool('browser')}
              disabled={!sessionId}
            />
            <SummaryRow
              icon={Terminal}
              label="Terminal"
              detail="Run commands in this workspace"
              onClick={openTool('terminal')}
              disabled={!sessionId}
            />
          </Section>

          {recentFiles.length > 0 && (
            <Section title={currentTurnChanges ? 'Latest turn' : 'Recent changes'}>
              {recentFiles.map((file) => {
                const path = recentPath(file)
                const turnFile = 'additions' in file ? file : null
                return (
                  <SummaryRow
                    key={path}
                    icon={CircleDot}
                    label={path.split('/').pop() ?? path}
                    detail={path}
                    onClick={() => {
                      onOpenFile?.(path)
                      openWorkbenchTool('source-control')
                    }}
                    trailing={turnFile && (
                      <span className="shrink-0 font-mono text-[10px] tabular-nums text-(--color-text-muted)">
                        {turnFile.additions != null && (
                          <span className="text-(--color-success)">+{turnFile.additions}</span>
                        )}
                        {turnFile.deletions != null && (
                          <span className="ml-1 text-(--color-error)">−{turnFile.deletions}</span>
                        )}
                      </span>
                    )}
                  />
                )
              })}
              {(
                currentTurnChanges?.files.length
                ?? files.length
              ) > recentFiles.length && (
                <button
                  type="button"
                  onClick={openTool('source-control')}
                  className="flex w-full items-center justify-center gap-1.5 px-3 py-2.5 text-[11px] font-medium text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                >
                  View all changes
                  <ArrowUpRight size={12} aria-hidden="true" />
                </button>
              )}
            </Section>
          )}
        </div>
      </div>
    </div>
  )
}
