import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { UiFlashcardsBlock } from './ui-block-types'

/**
 * Tap/click flip-cards (Intelligent UI showcase). The whole card is a
 * `<button>` so Enter/Space flip it for keyboard users; the 3D rotation is
 * a pure CSS transform with no transition under `prefers-reduced-motion`.
 */
export function UiFlashcards({ block }: { block: UiFlashcardsBlock }) {
  const cards = block.cards
  const [index, setIndex] = useState(0)
  const [flipped, setFlipped] = useState(false)
  const card = cards[index]
  const multiple = cards.length > 1

  const goTo = (next: number) => {
    setIndex(next)
    setFlipped(false)
  }

  return (
    <div className="rounded-md border border-(--color-border) bg-(--bg-card) p-3">
      {block.title && (
        <p className="mb-2 text-sm font-medium text-(--color-text)">{block.title}</p>
      )}
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-xs text-(--color-text-muted)" aria-live="polite">
          Card {index + 1} of {cards.length}
        </p>
        {multiple && (
          <div className="flex items-center gap-1">
            <button
              type="button"
              aria-label="Previous card"
              disabled={index === 0}
              onClick={() => goTo(index - 1)}
              className="inline-flex size-6 items-center justify-center rounded-sm border border-(--color-border) text-(--color-text-muted) transition-colors hover:bg-(--bg-key) disabled:pointer-events-none disabled:opacity-40"
            >
              <ChevronLeft size={14} aria-hidden />
            </button>
            <button
              type="button"
              aria-label="Next card"
              disabled={index === cards.length - 1}
              onClick={() => goTo(index + 1)}
              className="inline-flex size-6 items-center justify-center rounded-sm border border-(--color-border) text-(--color-text-muted) transition-colors hover:bg-(--bg-key) disabled:pointer-events-none disabled:opacity-40"
            >
              <ChevronRight size={14} aria-hidden />
            </button>
          </div>
        )}
      </div>
      <button
        type="button"
        aria-label="Flip card"
        aria-pressed={flipped}
        onClick={() => setFlipped((f) => !f)}
        className="group block w-full [perspective:800px]"
      >
        <div
          className={`relative min-h-24 transition-transform duration-500 [transform-style:preserve-3d] motion-reduce:transition-none group-focus-visible:ring-2 group-focus-visible:ring-(--focus-ring)/40 ${
            flipped ? '[transform:rotateY(180deg)]' : ''
          }`}
        >
          <span
            className="flex min-h-24 items-center justify-center rounded-md border border-(--color-border-strong) bg-(--bg-card) px-3 py-3 text-sm whitespace-pre-wrap text-(--color-text) [backface-visibility:hidden]"
            aria-hidden={flipped}
          >
            {card.front}
          </span>
          <span
            className="absolute inset-0 flex items-center justify-center rounded-md border border-(--color-border-strong) bg-(--bg-key) px-3 py-3 text-sm whitespace-pre-wrap text-(--color-text) [backface-visibility:hidden] [transform:rotateY(180deg)]"
            aria-hidden={!flipped}
          >
            {card.back}
          </span>
        </div>
      </button>
      <p className="mt-2 text-center text-[11px] text-(--color-text-muted)">
        Tap the card to flip
      </p>
    </div>
  )
}
