import { useEffect, useRef, useState } from 'react'
import { useI18n } from '@/i18n'
import { createMemoryState, flipMemoryCard, resolveMemoryMismatch } from './memory-logic'

interface MemoryGameProps { active: boolean }
const MARKS = ['◆', '●', '▲', '■', '✦', '⬟', '✚', '◈']

export function MemoryGame({ active }: MemoryGameProps) {
  const { t } = useI18n()
  const [state, setState] = useState(() => createMemoryState())
  const [focusIndex, setFocusIndex] = useState(0)
  const cardsRef = useRef<Array<HTMLButtonElement | null>>([])
  const mismatch = state.openCards.length === 2 && state.cards[state.openCards[0]].pair !== state.cards[state.openCards[1]].pair

  useEffect(() => {
    if (!mismatch || !active) return
    const timeout = window.setTimeout(() => setState((current) => resolveMemoryMismatch(current)), 700)
    return () => window.clearTimeout(timeout)
  }, [active, mismatch, state.openCards])

  const focus = (index: number) => {
    const next = (index + 16) % 16
    setFocusIndex(next)
    cardsRef.current[next]?.focus()
  }
  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!active) return
    const moves: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: 4, ArrowUp: -4 }
    if (event.key in moves) { event.preventDefault(); focus(focusIndex + moves[event.key]); return }
    if (event.key === 'Enter' || event.key === ' ') {
      const index = Number((event.target as HTMLElement).dataset.index)
      if (Number.isInteger(index)) { event.preventDefault(); setState((current) => flipMemoryCard(current, index)) }
    }
  }

  return (
    <section className="flex flex-col gap-3" aria-label={t('Memory Pairs game')}>
      <div className="flex items-center justify-between gap-3">
        <p className="font-mono text-xs text-(--color-text-muted)">{t('Pairs')}: {state.pairsFound}/8</p>
        <button type="button" className="rounded-md border border-(--color-border) px-2.5 py-1.5 text-xs hover:bg-(--bg-key) focus-visible:outline-2 focus-visible:outline-(--color-accent)" onClick={() => { setState(createMemoryState()); setFocusIndex(0) }}>{t('New game')}</button>
      </div>
      <div role="group" aria-label={t('Memory Pairs board')} onKeyDown={onKeyDown} className="mx-auto grid aspect-square w-full max-w-[18rem] grid-cols-4 gap-1.5 rounded-md border border-(--color-border) bg-(--bg-key) p-2">
        {state.cards.map((card, index) => (
          <button key={card.id} ref={(node) => { cardsRef.current[index] = node }} type="button" data-index={index} tabIndex={index === focusIndex ? 0 : -1}
            aria-label={card.matched ? t('Matched card') : card.revealed ? t('Revealed card {0}', [card.pair + 1]) : t('Hidden card')}
            aria-pressed={card.revealed || card.matched}
            onFocus={() => setFocusIndex(index)} onClick={() => setState((current) => flipMemoryCard(current, index))}
            className={`waiting-memory-card min-h-0 rounded-sm border font-mono text-xl font-semibold focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-(--color-accent) ${card.revealed || card.matched ? 'border-(--color-accent)/60 bg-(--bg-page) text-(--color-accent)' : 'border-(--color-border) bg-(--bg-page)/45 text-(--color-text-muted) hover:border-(--color-accent)/60'}`}>
            {card.revealed || card.matched ? MARKS[card.pair] : '·'}
          </button>
        ))}
      </div>
      <p aria-live="polite" className="text-xs text-(--color-text-muted)">{state.status === 'won' ? t('All pairs found — play again') : t('Use arrow keys to move, then Enter or Space to reveal a card.')}</p>
    </section>
  )
}
