import { useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '@/i18n'
import {
  advanceSnake,
  createSnakeState,
  setSnakeDirection,
  type GridPoint,
  type SnakeState,
} from './snake-logic'

interface SnakeGameProps {
  active: boolean
}

const DIRECTIONS: Record<string, GridPoint> = {
  ArrowUp: { x: 0, y: -1 }, w: { x: 0, y: -1 },
  ArrowDown: { x: 0, y: 1 }, s: { x: 0, y: 1 },
  ArrowLeft: { x: -1, y: 0 }, a: { x: -1, y: 0 },
  ArrowRight: { x: 1, y: 0 }, d: { x: 1, y: 0 },
}

export function SnakeGame({ active }: SnakeGameProps) {
  const { t } = useI18n()
  const [state, setState] = useState(() => createSnakeState())
  const [reducedMotion, setReducedMotion] = useState(() => (
    typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  ))
  const boardRef = useRef<HTMLDivElement>(null)
  const boardCells = useMemo(() => Array.from({ length: state.width * state.height }, (_, index) => index), [state.width, state.height])

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)')
    const updatePreference = (event: MediaQueryListEvent) => setReducedMotion(event.matches)
    preference.addEventListener('change', updatePreference)
    return () => preference.removeEventListener('change', updatePreference)
  }, [])

  useEffect(() => {
    if (!active || state.status !== 'playing') return
    const timer = window.setInterval(() => setState((current) => advanceSnake(current)), reducedMotion ? 480 : 320)
    return () => window.clearInterval(timer)
  }, [active, reducedMotion, state.status])

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!active || event.target !== event.currentTarget) return
    if (event.key === ' ') {
      event.preventDefault()
      setState((current) => current.status === 'playing'
        ? { ...current, status: 'ready' }
        : current.status === 'ready'
          ? { ...current, status: 'playing' }
          : current)
      return
    }
    const direction = DIRECTIONS[event.key] ?? DIRECTIONS[event.key.toLowerCase()]
    if (!direction) return
    event.preventDefault()
    setState((current) => setSnakeDirection(current, direction))
  }

  const head = state.body[0]
  const bodyCells = new Set(state.body.map(({ x, y }) => y * state.width + x))
  const headIndex = head.y * state.width + head.x
  const foodIndex = state.food.y * state.width + state.food.x

  const toggleRun = () => {
    setState((current) => {
      if (current.status === 'playing') return { ...current, status: 'ready' }
      if (current.status === 'ready') return { ...current, status: 'playing' }
      return createSnakeState()
    })
    if (state.status !== 'playing') boardRef.current?.focus()
  }

  return (
    <section className="flex flex-col gap-3" aria-label={t('Snake game')}>
      <div className="flex items-center justify-between gap-3">
        <p className="font-mono text-xs text-(--color-text-muted)">{t('Score')}: {state.score}</p>
        <div className="flex gap-2">
          <button type="button" className="rounded-md border border-(--color-border) px-2.5 py-1.5 text-xs hover:bg-(--bg-key) focus-visible:outline-2 focus-visible:outline-(--color-accent)" onClick={toggleRun}>
            {state.status === 'playing' ? t('Pause Snake') : state.status === 'ready' ? t('Start Snake') : t('Restart Snake')}
          </button>
          <button type="button" className="rounded-md border border-(--color-border) px-2.5 py-1.5 text-xs hover:bg-(--bg-key) focus-visible:outline-2 focus-visible:outline-(--color-accent)" onClick={() => setState(createSnakeState())}>
            {t('Restart')}
          </button>
        </div>
      </div>

      <div
        role="group"
        aria-label={t('Snake board')}
        ref={boardRef}
        tabIndex={0}
        onKeyDown={handleKeyDown}
        className="mx-auto grid aspect-[6/5] w-full max-w-[18rem] touch-manipulation rounded-md border border-(--color-border) bg-(--bg-key) p-2 outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent)/40"
        style={{ gridTemplateColumns: `repeat(${state.width}, minmax(0, 1fr))` }}
      >
        {boardCells.map((index) => {
          const isHead = index === headIndex
          const isBody = bodyCells.has(index) && !isHead
          const isFood = index === foodIndex
          return (
            <span
              key={index}
              data-testid={isHead ? 'snake-head' : undefined}
              data-x={isHead ? head.x : undefined}
              data-y={isHead ? head.y : undefined}
              aria-hidden="true"
              className={isHead
                ? 'm-px rounded-[2px] bg-(--color-accent)'
                : isBody
                  ? 'm-px rounded-[2px] bg-(--color-accent)/65'
                  : isFood
                    ? 'm-px rounded-[2px] border-2 border-(--color-accent)'
                    : 'm-px rounded-[2px] bg-(--bg-page)/40'}
            />
          )
        })}
      </div>
      <div className="flex items-center justify-between gap-3">
        <p aria-live="polite" className="min-h-5 text-xs text-(--color-text-muted)">
          {state.status === 'lost' ? t('Snake over — restart to play again') : state.status === 'won' ? t('Board cleared — you win') : reducedMotion ? t('Reduced motion: Snake moves every 480 ms') : t('Focus the board to use arrow keys or WASD. Press Space to pause.')}
        </p>
        <div className="grid grid-cols-3 gap-1" aria-label={t('Snake direction controls')}>
          <span />
          <DirectionButton label={t('Move up')} direction={{ x: 0, y: -1 }} onDirection={setState} />
          <span />
          <DirectionButton label={t('Move left')} direction={{ x: -1, y: 0 }} onDirection={setState} />
          <DirectionButton label={t('Move down')} direction={{ x: 0, y: 1 }} onDirection={setState} />
          <DirectionButton label={t('Move right')} direction={{ x: 1, y: 0 }} onDirection={setState} />
        </div>
      </div>
    </section>
  )
}

function DirectionButton({
  label,
  direction,
  onDirection,
}: {
  label: string
  direction: GridPoint
  onDirection: React.Dispatch<React.SetStateAction<SnakeState>>
}) {
  const symbol = direction.y < 0 ? '↑' : direction.y > 0 ? '↓' : direction.x < 0 ? '←' : '→'
  return (
    <button
      type="button"
      aria-label={label}
      className="size-9 rounded-md border border-(--color-border) bg-(--bg-page) text-sm hover:bg-(--bg-key) focus-visible:outline-2 focus-visible:outline-(--color-accent)"
      onClick={() => onDirection((state) => setSnakeDirection(state, direction))}
    >
      {symbol}
    </button>
  )
}
