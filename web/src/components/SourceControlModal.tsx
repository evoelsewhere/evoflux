import { useState, useEffect } from 'react'
import { GitCommit, GitBranch, History, Package, Archive, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { useGitChangesQuery, useGitConflictsQuery } from '@/queries/useGitQuery'
import { SourceControlConflictBanner } from './SourceControlConflictBanner'
import { SourceControlLocalChanges } from './SourceControlLocalChanges'
import { SourceControlCommit } from './SourceControlCommit'
import { SourceControlLog } from './SourceControlLog'
import { SourceControlBranches } from './SourceControlBranches'
import { SourceControlPushPull } from './SourceControlPushPull'
import { SourceControlStash } from './SourceControlStash'
import type { CodingProject } from '@/api/types'

type Section = 'changes' | 'commit' | 'log' | 'branches' | 'push-pull' | 'stash'

const SECTIONS: { key: Section; icon: typeof GitCommit; label: string }[] = [
  { key: 'changes', icon: GitCommit, label: 'Changes' },
  { key: 'commit', icon: GitCommit, label: 'Commit' },
  { key: 'log', icon: History, label: 'Log' },
  { key: 'branches', icon: GitBranch, label: 'Branches' },
  { key: 'push-pull', icon: Package, label: 'Push/Pull' },
  { key: 'stash', icon: Archive, label: 'Stash' },
]

function repoLabel(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

export interface SourceControlModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  workspace: string
  onWorkspaceChange?: (path: string) => void
  project?: CodingProject | null
  initialSection?: Section
  initialFilePath?: string | null
  onFileOpenInEditor?: (path: string) => void
}

export function SourceControlModal({
  open,
  onOpenChange,
  workspace,
  onWorkspaceChange,
  project,
  initialSection = 'changes',
  initialFilePath: _initialFilePath,
  onFileOpenInEditor,
}: SourceControlModalProps) {
  const [section, setSection] = useState<Section>(initialSection)

  useEffect(() => {
    if (open) setSection(initialSection) // eslint-disable-line react-hooks/set-state-in-effect
  }, [open, initialSection])

  const changesQuery = useGitChangesQuery(workspace, open)
  const conflictsQuery = useGitConflictsQuery(workspace, open)

  const branch = changesQuery.data?.branch
  const conflicts = conflictsQuery.data
  const hasConflicts = conflicts?.conflicted ?? false
  const siblingRepos = project?.workspaces.filter((w) => w.path !== workspace) ?? []
  const showRepoSwitcher = siblingRepos.length > 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="flex !h-[90dvh] !max-h-[90dvh] !w-[90vw] !max-w-[90vw] flex-col gap-0 overflow-hidden !rounded-lg p-0"
      >
        {/* Header */}
        <div className="flex shrink-0 items-center gap-3 border-b border-(--color-border) px-4 py-3">
          <h2 className="truncate text-sm font-semibold text-(--color-text)">
            Source Control
          </h2>
          <span className="truncate text-xs text-(--color-text-subtle)">
            {repoLabel(workspace)}
          </span>
          {branch && (
            <span className="shrink-0 rounded-full bg-(--bg-key) px-2 py-0.5 text-[11px] font-medium text-(--color-text-muted)">
              {branch}
            </span>
          )}
          {changesQuery.data && (changesQuery.data.ahead > 0 || changesQuery.data.behind > 0) && (
            <span className="shrink-0 text-[11px] text-(--color-text-subtle)">
              {changesQuery.data.ahead > 0 && `↑${changesQuery.data.ahead}`}
              {changesQuery.data.ahead > 0 && changesQuery.data.behind > 0 && ' '}
              {changesQuery.data.behind > 0 && `↓${changesQuery.data.behind}`}
            </span>
          )}
          <div className="flex-1" />
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="flex h-7 w-7 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
          >
            <X size={16} />
          </button>
        </div>

        {/* Conflict banner */}
        {hasConflicts && (
          <SourceControlConflictBanner
            conflicts={conflicts!}
            onViewConflicts={() => setSection('changes')}
          />
        )}

        {/* Body: rail + content */}
        <div className="flex min-h-0 flex-1">
          {/* Repo switcher rail */}
          {showRepoSwitcher && (
            <div className="flex w-10 shrink-0 flex-col items-center gap-1 border-r border-(--color-border) bg-(--bg-key)/30 py-2">
              {project!.workspaces.map((ws) => (
                <button
                  key={ws.path}
                  type="button"
                  onClick={() => onWorkspaceChange?.(ws.path)}
                  title={ws.display_name || ws.name || ws.path}
                  className={cn(
                    'flex h-7 w-7 items-center justify-center rounded text-[10px] font-bold transition-colors',
                    ws.path === workspace
                      ? 'bg-(--color-accent) text-white'
                      : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
                  )}
                >
                  {(ws.display_name || ws.name || repoLabel(ws.path)).charAt(0).toUpperCase()}
                </button>
              ))}
            </div>
          )}

          {/* Section icon rail */}
          <div className="flex w-10 shrink-0 flex-col items-center gap-1 border-r border-(--color-border) bg-(--bg-key)/30 py-2">
            {SECTIONS.map(({ key, icon: Icon, label }) => (
              <button
                key={key}
                type="button"
                onClick={() => setSection(key)}
                title={label}
                className={cn(
                  'flex h-7 w-7 items-center justify-center rounded transition-colors',
                  section === key
                    ? 'bg-(--bg-key) text-(--color-accent)'
                    : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
                )}
              >
                <Icon size={14} />
              </button>
            ))}
          </div>

          {/* Content */}
          <div className="min-w-0 flex-1 overflow-hidden">
            {section === 'changes' && (
              <SourceControlLocalChanges
                workspace={workspace}
                onFileOpenInEditor={onFileOpenInEditor}
              />
            )}
            {section === 'commit' && (
              <SourceControlCommit workspace={workspace} />
            )}
            {section === 'log' && (
              <SourceControlLog workspace={workspace} />
            )}
            {section === 'branches' && (
              <SourceControlBranches workspace={workspace} />
            )}
            {section === 'push-pull' && (
              <SourceControlPushPull workspace={workspace} />
            )}
            {section === 'stash' && (
              <SourceControlStash workspace={workspace} />
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
