import { useState } from 'react'
import { useI18n } from '@/i18n'
import { create2048State, get2048MergeCells, move2048, type Game2048Direction } from './2048-logic'

interface Game2048Props {
  active: boolean
}

const DIRECTIONS: Record<string, Game2048Direction> = {
  ArrowUp: 'up', ArrowRight: 'right', ArrowDown: 'down', ArrowLeft: 'left',
}

function tileOrigins(previous: number[], next: number[], direction: Game2048Direction) {
  const origins: Record<number, { x: number; y: number }> = {}
  const used = new Set<number>()
  next.forEach((value, destination) => {
    if (!value || previous[destination] === value) return
    const row = Math.floor(destination / 4)
    const column = destination % 4
    const candidates = previous.flatMap((candidateValue, source) => {
      if (candidateValue !== value || used.has(source)) return []
      const sourceRow = Math.floor(source / 4)
      const sourceColumn = source % 4
      const upstream = direction === 'down' ? sourceColumn === column && sourceRow < row
        : direction === 'up' ? sourceColumn === column && sourceRow > row
          : direction === 'right' ? sourceRow === row && sourceColumn < column
            : sourceRow === row && sourceColumn > column
      return upstream ? [source] : []
    }).sort((a, b) => Math.abs(a - destination) - Math.abs(b - destination))
    const source = candidates[0]
    if (source === undefined) return
    used.add(source)
    origins[destination] = { x: source % 4 - column, y: Math.floor(source / 4) - row }
  })
  return origins
}

export function Game2048({ active }: Game2048Props) {
  const { t } = useI18n()
  const [state, setState] = useState(() => create2048State())
  const [moveCount, setMoveCount] = useState(0)
  const [motion, setMotion] = useState<{ id: number; direction: Game2048Direction; merged: number[]; origins: Record<number, { x: number; y: number }>; previous: number[] } | null>(null)

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!active || event.target !== event.currentTarget) return
    const direction = DIRECTIONS[event.key]
    if (!direction) return
    event.preventDefault()
    const next = move2048(state, direction)
    if (next === state) return
    const merged = get2048MergeCells(state.board, direction)
    setMotion((current) => ({ id: (current?.id ?? 0) + 1, direction, merged, origins: tileOrigins(state.board, next.board, direction), previous: state.board }))
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
            setMotion(null)
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
          const moved = Boolean(value && motion && motion.previous[index] !== value)
          const animationClass = !motion || !moved ? '' : motion.merged.includes(index) ? 'waiting-2048-merge' : motion.origins[index] ? 'waiting-2048-slide' : 'waiting-2048-spawn'
          return (
            <span
              key={`${index}-${motion?.id ?? 0}`}
              role="img"
              aria-label={value ? t('Tile {0} at row {1}, column {2}', [value, row, column]) : t('Empty row {0}, column {1}', [row, column])}
              data-testid={`2048-cell-${index}`}
              data-motion-direction={value && motion ? motion.direction : undefined}
              style={motion?.origins[index] ? {
                '--waiting-offset-x': `calc(${motion.origins[index].x * 100}% + ${motion.origins[index].x * 0.375}rem)`,
                '--waiting-offset-y': `calc(${motion.origins[index].y * 100}% + ${motion.origins[index].y * 0.375}rem)`,
              } as React.CSSProperties : undefined}
              className={`flex min-h-0 items-center justify-center rounded-sm border font-mono text-lg font-semibold tabular-nums ${value ? `border-(--color-accent)/60 bg-(--bg-page) text-(--color-accent) ${animationClass}` : 'border-(--color-border) bg-(--bg-page)/45 text-transparent'}`}
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
