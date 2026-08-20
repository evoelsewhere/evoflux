import { ChevronUp, RefreshCw } from 'lucide-react'

import { cn } from '@/lib/utils'
import { useTeamStore } from '@/stores/useTeamStore'

interface TranscriptHistoryControlProps {
  allowServerHistory?: boolean
  compact?: boolean
  hiddenTurnCount: number
  revealStep: number
  onLoadOlder: () => void
  onRevealLoaded: () => void
}

/**
 * One entry point for both client-hidden turns and server-paginated history.
 *
 * The server cursor is intentionally represented even when the current page
 * starts in the middle of a long assistant turn. In that case there are no
 * locally hidden turns, but older durable messages still need a reachable UI.
 */
export function TranscriptHistoryControl({
  allowServerHistory = true,
  compact = false,
  hiddenTurnCount,
  revealStep,
  onLoadOlder,
  onRevealLoaded,
}: TranscriptHistoryControlProps) {
  const hasMore = useTeamStore((state) => state.hasMore)
  const loading = useTeamStore((state) => state._loadingOlder)
  const error = useTeamStore((state) => state.historyLoadError)

  const hasLoadedTurns = hiddenTurnCount > 0
  const canLoadServerHistory = allowServerHistory && (hasMore || loading || Boolean(error))
  if (!hasLoadedTurns && !canLoadServerHistory) return null

  const label = hasLoadedTurns
    ? `Show earlier messages · ${hiddenTurnCount} hidden`
    : loading
      ? 'Loading earlier messages…'
      : error
        ? 'Retry earlier messages'
        : 'Load earlier messages'
  const ariaLabel = hasLoadedTurns
    ? `Show ${Math.min(revealStep, hiddenTurnCount)} earlier turns`
    : label

  return (
    <div className={cn('flex justify-center', compact ? 'pb-1' : 'py-2')}>
      <button
        type="button"
        disabled={loading}
        onClick={hasLoadedTurns ? onRevealLoaded : onLoadOlder}
        className={cn(
          'inline-flex items-center gap-1 rounded-full border border-(--color-border) bg-(--bg-card) text-xs text-(--color-text-2) transition-colors',
          'hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:ring-2 focus-visible:ring-(--focus-ring) focus-visible:outline-none',
          'disabled:cursor-wait disabled:opacity-70',
          compact ? 'min-h-8 px-2.5 py-1' : 'min-h-10 px-3 py-1.5',
        )}
        aria-label={ariaLabel}
        title={error ?? undefined}
      >
        {loading ? (
          <RefreshCw className="animate-spin" size={compact ? 12 : 13} aria-hidden="true" />
        ) : (
          <ChevronUp size={compact ? 12 : 13} aria-hidden="true" />
        )}
        {label}
      </button>
    </div>
  )
}
