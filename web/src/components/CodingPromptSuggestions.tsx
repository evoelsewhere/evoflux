import { Sparkles } from 'lucide-react'

interface CodingPromptSuggestionsProps {
  suggestions: readonly string[]
  onSuggestion?: (suggestion: string) => void
}

/** Shared prompt starters for coding empty states. */
export function CodingPromptSuggestions({
  suggestions,
  onSuggestion,
}: CodingPromptSuggestionsProps) {
  return (
    <div className="mt-4 border-t border-(--color-border-subtle) pt-3">
      <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-(--color-text-subtle)">
        <Sparkles size={11} className="text-(--color-accent)" aria-hidden="true" />
        Try asking
      </div>
      <div className="grid gap-1.5 sm:grid-cols-2">
        {suggestions.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            onClick={() => onSuggestion?.(suggestion)}
            className="rounded-lg border border-(--color-border-subtle) bg-(--bg-page)/55 px-2.5 py-2 text-left text-[11px] text-(--color-text-2) transition-colors hover:border-(--color-accent)/40 hover:bg-(--color-accent)/8 hover:text-(--color-text) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)"
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  )
}
