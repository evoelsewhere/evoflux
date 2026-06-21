/**
 * CompactionDivider — inline marker rendered when the summarisation hook
 * compacts the session's context window.
 *
 * Two visual elements:
 *   1. A horizontal-rule + centred label ("Session compacting…" /
 *      "Session compacted" / "Compaction failed") so users see where in
 *      the transcript context was trimmed.
 *   2. (Optional) the summary body itself rendered as Markdown beneath
 *      the divider — when ``summary`` is non-empty. The body is the
 *      authoritative artefact of what got compacted into; surfacing it
 *      lets the user audit what the LLM will see going forward.
 *
 * While ``state === 'compacting'`` the body streams in via SSE
 * ``summarization_content`` deltas (see useTeamStore reducer). The
 * divider re-renders on every delta, so the user sees the summary
 * being written in real time.
 */
import { LazyMarkdownBlock } from '@/utils/LazyMarkdownBlock'

interface CompactionDividerProps {
  state: 'compacting' | 'compacted'
  error?: boolean
  /** Summary body. Streams during ``compacting``; final text after ``compacted``. */
  summary?: string
  /** Forwarded to ``MarkdownBlock`` for in-prose attachment / image resolution. */
  sessionId?: string
}

export function CompactionDivider({ state, error, summary, sessionId }: CompactionDividerProps) {
  const label = error
    ? 'Compaction failed'
    : state === 'compacting'
      ? 'Session compacting'
      : 'Session compacted'

  const tone = error
    ? 'text-(--color-danger)'
    : state === 'compacting'
      ? 'text-(--color-text-subtle)'
      : 'text-(--color-text-2)'

  const trimmed = summary?.trim() ?? ''
  const showBody = trimmed.length > 0 && !error

  return (
    <div role="region" aria-label={label} className="my-4 space-y-3">
      <div className="flex items-center gap-3">
        <span className="h-px flex-1 bg-(--color-border)" aria-hidden />
        <span className={`font-mono text-xs ${tone}`}>
          {label}
          {state === 'compacting' && !error && (
            <span className="ml-1 inline-block animate-pulse">…</span>
          )}
        </span>
        <span className="h-px flex-1 bg-(--color-border)" aria-hidden />
      </div>

      {showBody && (
        // Rendered as plain assistant-style prose (no card chrome): same look
        // as a regular assistant text block, just dimmed via --color-text-2
        // to signal it is a derived/system artefact rather than a fresh reply.
        <div className="text-sm text-(--color-text-2)">
          <LazyMarkdownBlock content={trimmed} sessionId={sessionId} />
        </div>
      )}
    </div>
  )
}
