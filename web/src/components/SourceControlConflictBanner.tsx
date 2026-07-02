import { AlertTriangle, XCircle, ArrowRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { GitConflictsResponse } from '@/api/types'

export interface SourceControlConflictBannerProps {
  conflicts: GitConflictsResponse
  onContinue?: () => void
  onAbort?: () => void
  onViewConflicts?: () => void
  className?: string
}

export function SourceControlConflictBanner({
  conflicts,
  onContinue,
  onAbort,
  onViewConflicts,
  className,
}: SourceControlConflictBannerProps) {
  if (!conflicts.conflicted) return null

  return (
    <div
      className={cn(
        'flex items-center gap-3 border-b border-red-500/30 bg-red-500/10 px-4 py-2.5',
        className,
      )}
    >
      <AlertTriangle size={16} className="shrink-0 text-red-400" />
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium text-red-300">
          {conflicts.operation
            ? `${conflicts.operation} has conflicts`
            : 'Merge conflicts detected'}
        </p>
        <p className="text-[11px] text-red-300/70">
          {conflicts.files.length} conflicted {conflicts.files.length === 1 ? 'file' : 'files'}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {onViewConflicts && (
          <button
            type="button"
            onClick={onViewConflicts}
            className="flex items-center gap-1 rounded px-2 py-1 text-[11px] text-red-300 hover:bg-red-500/20"
          >
            View files <ArrowRight size={10} />
          </button>
        )}
        {onContinue && (
          <button
            type="button"
            onClick={onContinue}
            className="rounded bg-green-600 px-2 py-1 text-[11px] font-medium text-white hover:bg-green-500"
          >
            Continue
          </button>
        )}
        {onAbort && (
          <button
            type="button"
            onClick={onAbort}
            className="flex items-center gap-1 rounded px-2 py-1 text-[11px] text-red-300 hover:bg-red-500/20"
          >
            <XCircle size={11} /> Abort
          </button>
        )}
      </div>
    </div>
  )
}
