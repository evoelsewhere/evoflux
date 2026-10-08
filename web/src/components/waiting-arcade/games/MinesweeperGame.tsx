import { useRef, useState } from 'react'
import { useI18n } from '@/i18n'
import { createMinefield, revealMineCell, toggleMineFlag, type MinefieldState } from './minesweeper-logic'

interface MinesweeperGameProps {
  active: boolean
}

function createRandomMinefield(): MinefieldState {
  const indices = new Set<number>([14])
  while (indices.size < 5) {
    const candidate = Math.floor(Math.random() * 36)
    if (candidate !== 0 && candidate !== 21) indices.add(candidate)
  }
  return createMinefield([...indices])
}

export function MinesweeperGame({ active }: MinesweeperGameProps) {
  const { t } = useI18n()
  const [state, setState] = useState(() => createRandomMinefield())
  const [started, setStarted] = useState(false)
  const [mode, setMode] = useState<'reveal' | 'flag'>('reveal')
  const [focusedCell, setFocusedCell] = useState(0)
  const cellRefs = useRef<Array<HTMLButtonElement | null>>([])
  const flags = state.cells.filter((cell) => cell.flagged).length

  const restart = () => {
    setState(createRandomMinefield())
    setStarted(true)
    setMode('reveal')
  }

  const onCellClick = (index: number) => {
    if (!active || !started) return
    setFocusedCell(index)
    setState((current) => mode === 'flag' ? toggleMineFlag(current, index) : revealMineCell(current, index))
  }

  const onCellKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    const row = Math.floor(index / 6)
    const column = index % 6
    const nextIndex = event.key === 'ArrowUp' ? Math.max(0, row - 1) * 6 + column
      : event.key === 'ArrowDown' ? Math.min(5, row + 1) * 6 + column
        : event.key === 'ArrowLeft' ? row * 6 + Math.max(0, column - 1)
          : event.key === 'ArrowRight' ? row * 6 + Math.min(5, column + 1)
            : null
    if (nextIndex === null) return
    event.preventDefault()
    setFocusedCell(nextIndex)
    cellRefs.current[nextIndex]?.focus()
  }

  return (
    <section className="flex flex-col gap-3" aria-label={t('Minesweeper Mini game')}>
      <div className="flex items-center justify-between gap-3">
        <p className="font-mono text-xs text-(--color-text-muted)">{t('Flags')}: {flags}/5</p>
        <button type="button" className="rounded-md border border-(--color-border) px-2.5 py-1.5 text-xs hover:bg-(--bg-key) focus-visible:outline-2 focus-visible:outline-(--color-accent)" onClick={restart}>
          {started ? t('Restart Minesweeper') : t('Start Minesweeper')}
        </button>
      </div>
      <div className="flex gap-2" aria-label={t('Minesweeper controls')}>
        <button type="button" aria-pressed={mode === 'reveal'} aria-label={t('Reveal mode')} onClick={() => setMode('reveal')} className="flex-1 rounded-md border border-(--color-border) px-2 py-1.5 text-xs focus-visible:outline-2 focus-visible:outline-(--color-accent) aria-pressed:border-(--color-accent) aria-pressed:bg-(--color-accent)/10">{t('Reveal')}</button>
        <button type="button" aria-pressed={mode === 'flag'} aria-label={t('Flag mode')} onClick={() => setMode('flag')} className="flex-1 rounded-md border border-(--color-border) px-2 py-1.5 text-xs focus-visible:outline-2 focus-visible:outline-(--color-accent) aria-pressed:border-(--color-accent) aria-pressed:bg-(--color-accent)/10">{t('Flag')}</button>
      </div>
      <p className="text-[11px] leading-relaxed text-(--color-text-muted)">{t('Use arrow keys to move, then Enter or Space to reveal or flag.')}</p>
      <div role="group" aria-label={t('Minesweeper board')} className="mx-auto grid w-full max-w-[18rem] grid-cols-6 gap-1.5">
        {state.cells.map((cell, index) => {
          const row = Math.floor(index / 6) + 1
          const column = (index % 6) + 1
          const label = cell.flagged
            ? t('Cell {0}, {1} flagged', [row, column])
            : cell.revealed
              ? t('Cell {0}, {1} revealed{2}', [row, column, cell.mine ? `, ${t('mine')}` : cell.adjacent ? `, ${cell.adjacent}` : ''])
              : t('Cell {0}, {1} hidden', [row, column])
          return (
            <button
              key={index}
              type="button"
              aria-label={label}
              tabIndex={index === focusedCell ? 0 : -1}
              ref={(element) => { cellRefs.current[index] = element }}
              onFocus={() => setFocusedCell(index)}
              onKeyDown={(event) => onCellKeyDown(event, index)}
              disabled={!started || state.status === 'won' || state.status === 'lost'}
              onClick={() => onCellClick(index)}
              className={`aspect-square min-h-10 rounded-sm border text-sm font-mono font-semibold focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-(--color-accent) focus-visible:outline-offset-1 disabled:cursor-default ${cell.revealed ? 'border-(--color-border) bg-(--bg-key)' : 'border-(--color-border-strong) bg-(--bg-page) hover:border-(--color-accent)'} ${cell.flagged ? 'text-(--color-accent)' : 'text-(--color-text)'}`}
            >
              {cell.flagged ? '⚑' : cell.revealed ? cell.mine ? '✹' : cell.adjacent || '' : '·'}
            </button>
          )
        })}
      </div>
      <p aria-live="polite" className="min-h-5 text-xs text-(--color-text-muted)">
        {state.status === 'won' ? t('Board cleared — you win') : state.status === 'lost' ? t('Mine hit — restart to try again') : !started ? t('Start a round when you are ready') : t('No timer — the board waits for you')}
      </p>
    </section>
  )
}
