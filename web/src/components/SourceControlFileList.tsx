import { FileText, RotateCcw } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ChangedFile } from '@/api/types'

const STATUS_MAP: Record<ChangedFile['status'], { label: string; color: string }> = {
  modified: { label: 'M', color: 'text-amber-400' },
  added: { label: 'A', color: 'text-green-400' },
  deleted: { label: 'D', color: 'text-red-400' },
  renamed: { label: 'R', color: 'text-blue-400' },
  untracked: { label: '??', color: 'text-(--color-text-muted)' },
  unmerged: { label: 'U', color: 'text-red-400' },
}

export interface SourceControlFileListProps {
  files: ChangedFile[]
  selectedPath?: string | null
  onSelect?: (path: string) => void
  onStage?: (path: string) => void
  onUnstage?: (path: string) => void
  onDiscard?: (path: string) => void
  showStageControls?: boolean
  showDiscard?: boolean
}

export function SourceControlFileList({
  files,
  selectedPath,
  onSelect,
  onStage,
  onUnstage,
  onDiscard,
  showStageControls = true,
  showDiscard = false,
}: SourceControlFileListProps) {
  const sorted = [...files].sort((a, b) => {
    const aConflict = a.status === 'unmerged' ? 0 : 1
    const bConflict = b.status === 'unmerged' ? 0 : 1
    if (aConflict !== bConflict) return aConflict - bConflict
    return a.path.localeCompare(b.path)
  })

  if (sorted.length === 0) {
    return (
      <p className="px-2 py-4 text-xs text-(--color-text-subtle)">No changed files</p>
    )
  }

  return (
    <div className="space-y-0.5">
      {sorted.map((file) => {
        const info = STATUS_MAP[file.status]
        const isConflict = file.status === 'unmerged'
        const isSelected = file.path === selectedPath
        return (
          <div
            key={file.path}
            className={cn(
              'group flex items-center gap-1.5 rounded px-2 py-1 transition-colors',
              isSelected
                ? 'bg-(--bg-key) text-(--color-accent)'
                : 'hover:bg-(--bg-key)',
            )}
          >
            {showStageControls && (
              <input
                type="checkbox"
                checked={file.staged}
                onChange={() =>
                  file.staged ? onUnstage?.(file.path) : onStage?.(file.path)
                }
                onClick={(e) => e.stopPropagation()}
                className="h-3.5 w-3.5 shrink-0 cursor-pointer accent-(--color-accent)"
              />
            )}
            <button
              type="button"
              onClick={() => onSelect?.(file.path)}
              className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
            >
              <FileText
                size={12}
                className={cn(
                  'shrink-0',
                  isConflict ? 'text-red-400' : 'text-(--color-text-subtle)',
                )}
              />
              <span
                className="min-w-0 flex-1 truncate font-mono text-xs text-(--color-text)"
                title={file.old_path ? `${file.old_path} → ${file.path}` : file.path}
              >
                {file.old_path ? `${file.old_path} → ${file.path}` : file.path}
              </span>
              <span
                className={cn(
                  'shrink-0 rounded px-1 font-mono text-[10px] font-semibold',
                  isConflict
                    ? 'bg-red-500/20 text-red-400'
                    : `${info.color}`,
                )}
              >
                {info.label}
              </span>
            </button>
            {showDiscard && file.status !== 'untracked' && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onDiscard?.(file.path)
                }}
                className="hidden shrink-0 rounded p-0.5 text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-error) group-hover:flex"
                aria-label="Discard changes"
                title="Discard changes"
              >
                <RotateCcw size={11} />
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}
