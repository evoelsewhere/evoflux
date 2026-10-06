import { useState } from 'react'
import { useI18n } from '@/i18n'
import { create2048State, move2048, type Game2048Direction } from './2048-logic'

interface Game2048Props {
  active: boolean
}

const DIRECTIONS: Record<string, Game2048Direction> = {
  ArrowUp: 'up', ArrowRight: 'right', ArrowDown: 'down', ArrowLeft: 'left',
}

export function Game2048({ active }: Game2048Props) {
  const { t } = useI18n()
  const [state, setState] = useState(() => create2048State())
  const [moveCount, setMoveCount] = useState(0)

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!active || event.target !== event.currentTarget) return
    const direction = DIRECTIONS[event.key]
    if (!direction) return
    event.preventDefault()
    const next = move2048(state, direction)
    if (next === state) return
    setState(next)
    setMoveCount((count) => count + 1)
  }

  const status = state.status === 'won'
    ? t('You reached 2048 — start a new game to play again')
    : state.status === 'over'
      ? t('No more moves — start a new game')
      : t('Move with the arrow keys after focusing the board')

  return (
    <section className="flex flex-col gap-3" aria-label={t('2048 game')}>
      <div className="flex items-center justify-between gap-3">
        <p className="font-mono text-xs text-(--color-text-muted)">{t('Score')}: {state.score}</p>
        <button
          type="button"
          className="rounded-md border border-(--color-border) px-2.5 py-1.5 text-xs hover:bg-(--bg-key) focus-visible:outline-2 focus-visible:outline-(--color-accent)"
          onClick={() => {
            setState(create2048State())
            setMoveCount(0)
          }}
        >
          {t('New game')}
        </button>
      </div>
      <div
        role="group"
        aria-label={t('2048 board')}
        aria-describedby="waiting-arcade-2048-instructions"
        tabIndex={0}
        onKeyDown={handleKeyDown}
        className="mx-auto grid aspect-square w-full max-w-[18rem] grid-cols-4 gap-1.5 rounded-md border border-(--color-border) bg-(--bg-key) p-2 outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent)/60"
      >
        {state.board.map((value, index) => {
          const row = Math.floor(index / 4) + 1
          const column = index % 4 + 1
          return (
            <span
              key={index}
              role="img"
              aria-label={value ? t('Tile {0} at row {1}, column {2}', [value, row, column]) : t('Empty row {0}, column {1}', [row, column])}
              data-testid={`2048-cell-${index}`}
              className={`flex min-h-0 items-center justify-center rounded-sm border font-mono text-lg font-semibold tabular-nums ${value ? 'border-(--color-accent)/60 bg-(--bg-page) text-(--color-accent)' : 'border-(--color-border) bg-(--bg-page)/45 text-transparent'}`}
            >
              {value || '·'}
            </span>
          )
        })}
      </div>
      <p id="waiting-arcade-2048-instructions" className="text-xs text-(--color-text-muted)">
        {state.status === 'playing' ? t('Move with the arrow keys after focusing the board') : status}
      </p>
      <p aria-live="polite" className="sr-only">
        {state.status === 'playing' && moveCount > 0 ? t('Move {0}, score {1}', [moveCount, state.score]) : state.status === 'playing' ? '' : status}
      </p>
    </section>
  )
}
