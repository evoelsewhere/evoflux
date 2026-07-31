import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  ChevronDown,
  ChevronUp,
  Loader2,
  RotateCcw,
  SquarePlus,
} from 'lucide-react'

import type { TurnChangedFile, TurnChangesPending } from '@/api/types'
import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'
import { useTeamStore } from '@/stores/useTeamStore'
import { useUIStore } from '@/stores/useUIStore'

const COLLAPSED_FILE_COUNT = 3

function fileStatusLabel(status: TurnChangedFile['status']): string {
  if (status === 'added') return 'Added'
  if (status === 'removed') return 'Removed'
  return 'Modified'
}

function FileChangeRow({
  file,
  compact,
  onReview,
}: {
  file: TurnChangedFile
  compact: boolean
  onReview: () => void
}) {
  const hasStats = file.additions != null || file.deletions != null

  return (
    <button
      type="button"
      onClick={onReview}
      className={cn(
        'group flex w-full items-center gap-3 text-left transition-colors hover:bg-(--bg-key)/55 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-(--focus-ring)/35 focus-visible:outline-none',
        compact ? 'min-h-9 px-3 py-1.5' : 'min-h-10 px-3.5 py-2',
      )}
      title={`Review ${file.path}`}
    >
      <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-(--color-text-2)">
        {file.path}
      </span>
      {hasStats ? (
        <span className="flex shrink-0 items-center gap-1.5 font-mono text-[11px] tabular-nums">
          <span className="text-(--color-success)">+{file.additions ?? 0}</span>
          <span className="text-(--color-error)">−{file.deletions ?? 0}</span>
        </span>
      ) : (
        <span className="shrink-0 text-[10px] font-medium text-(--color-text-subtle)">
          {fileStatusLabel(file.status)}
        </span>
      )}
    </button>
  )
}

export function TurnChangesCard({
  changes,
  compact = false,
}: {
  changes: TurnChangesPending
  compact?: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const [undoing, setUndoing] = useState(false)
  const undoTeam = useTeamStore((state) => state.undoTeam)
  const dismissTurnChanges = useTeamStore((state) => state.dismissTurnChanges)
  const openGitChanges = useUIStore((state) => state.openGitChanges)
  const preset = useMotionPreset()

  const fileCount = changes.files.length
  const hiddenCount = Math.max(0, fileCount - COLLAPSED_FILE_COUNT)
  const visibleFiles = expanded
    ? changes.files
    : changes.files.slice(0, COLLAPSED_FILE_COUNT)

  const reviewChanges = () => {
    dismissTurnChanges()
    openGitChanges()
  }

  const undoChanges = async () => {
    if (undoing) return
    setUndoing(true)
    try {
      const response = await undoTeam()
      if (response) {
        useTeamStore.setState({
          turnChanges: null,
          turnChangesOpen: false,
        })
      }
    } finally {
      setUndoing(false)
    }
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 6 * preset.distance }}
      animate={{ opacity: 1, y: 0 }}
      transition={preset.transition}
      aria-label={`${fileCount} files edited this turn`}
      className={cn(
        'overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-card) shadow-[0_1px_2px_rgba(0,0,0,0.08)]',
        compact ? 'mt-2' : 'mt-3',
      )}
    >
      <header
        className={cn(
          'flex items-center gap-3 border-b border-(--color-border)',
          compact ? 'px-3 py-2.5' : 'px-3.5 py-3',
        )}
      >
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-(--color-border) bg-(--bg-key) text-(--color-text-2)">
          <SquarePlus size={16} aria-hidden="true" />
        </span>

        <span className="min-w-0 flex-1">
          <span className="block truncate text-xs font-semibold text-(--color-text)">
            Edited {fileCount} {fileCount === 1 ? 'file' : 'files'}
          </span>
          <span className="mt-0.5 flex items-center gap-1.5 font-mono text-[11px] tabular-nums">
            <span className="text-(--color-success)">+{changes.additions}</span>
            <span className="text-(--color-error)">−{changes.deletions}</span>
          </span>
        </span>

        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={() => void undoChanges()}
            disabled={undoing}
            className="focus-ring-control inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:cursor-wait disabled:opacity-60"
          >
            {undoing
              ? <Loader2 size={13} className="animate-spin" aria-hidden="true" />
              : <RotateCcw size={13} aria-hidden="true" />}
            <span className={cn(compact && 'hidden sm:inline')}>Undo</span>
          </button>
          <button
            type="button"
            onClick={reviewChanges}
            className="focus-ring-control inline-flex h-8 items-center rounded-lg border border-(--color-border-strong) bg-(--bg-key)/70 px-3 text-xs font-medium text-(--color-text) transition-colors hover:bg-(--bg-hover)"
          >
            Review
          </button>
        </div>
      </header>

      <div className="divide-y divide-(--color-border-subtle)">
        {visibleFiles.map((file) => (
          <FileChangeRow
            key={file.path}
            file={file}
            compact={compact}
            onReview={reviewChanges}
          />
        ))}
      </div>

      {hiddenCount > 0 && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className="focus-ring-control flex h-9 w-full items-center gap-1.5 border-t border-(--color-border-subtle) bg-(--bg-key)/55 px-3.5 text-left text-[11px] font-medium text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
        >
          <span>{expanded ? 'Show fewer files' : `Show ${hiddenCount} more files`}</span>
          {expanded
            ? <ChevronUp size={13} aria-hidden="true" />
            : <ChevronDown size={13} aria-hidden="true" />}
        </button>
      )}
    </motion.section>
  )
}
