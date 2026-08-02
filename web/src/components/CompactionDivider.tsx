/**
 * CompactionDivider — inline marker rendered when the summarisation hook
 * compacts the session's context window.
 *
 * Renders only a horizontal-rule + centred lifecycle label. The generated
 * summary remains internal model context and is not chat output.
 */
interface CompactionDividerProps {
  state: 'compacting' | 'compacted'
  error?: boolean
}

export function CompactionDivider({ state, error }: CompactionDividerProps) {
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

  return (
    <div role="region" aria-label={label} className="my-4">
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

    </div>
  )
}
