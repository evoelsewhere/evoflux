import { useRef, useState } from 'react'
import { useI18n } from '@/i18n'
import {
  chooseTicTacToeMove,
  createTicTacToeState,
  playTicTacToeCell,
  type TicTacToeState,
} from './tic-tac-toe-logic'

interface TicTacToeGameProps {
  active: boolean
}

export function TicTacToeGame({ active }: TicTacToeGameProps) {
  const { t } = useI18n()
  const [state, setState] = useState<TicTacToeState>(() => createTicTacToeState())
  const [started, setStarted] = useState(false)
  const [focusedCell, setFocusedCell] = useState(0)
  const cellRefs = useRef<Array<HTMLButtonElement | null>>([])

  const restart = () => {
    setState(createTicTacToeState())
    setStarted(true)
  }

  const play = (index: number) => {
    if (!active || !started || state.status !== 'playing') return
    const afterPlayer = playTicTacToeCell(state, index, 'X')
    if (afterPlayer === state || afterPlayer.status !== 'playing') {
      setState(afterPlayer)
      return
    }
    const botMove = chooseTicTacToeMove(afterPlayer.board, 'O')
    setState(botMove === null ? afterPlayer : playTicTacToeCell(afterPlayer, botMove, 'O'))
  }

  const onCellKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    const row = Math.floor(index / 3)
    const column = index % 3
    const nextIndex = event.key === 'ArrowUp' ? Math.max(0, row - 1) * 3 + column
      : event.key === 'ArrowDown' ? Math.min(2, row + 1) * 3 + column
        : event.key === 'ArrowLeft' ? row * 3 + Math.max(0, column - 1)
          : event.key === 'ArrowRight' ? row * 3 + Math.min(2, column + 1)
            : null
    if (nextIndex === null) return
    event.preventDefault()
    setFocusedCell(nextIndex)
    cellRefs.current[nextIndex]?.focus()
  }

  const status = state.status === 'draw'
    ? t('Draw game')
    : state.status === 'won'
      ? state.winner === 'X' ? t('You win') : t('Local opponent wins')
      : t('Your turn — you are X')

  return (
    <section className="flex flex-col gap-3" aria-label={t('Tic-tac-toe game')}>
      <div className="flex items-center justify-between gap-3">
        <p aria-live="polite" className="text-xs text-(--color-text-muted)">{started ? status : t('Play a quick local match')}</p>
        <button type="button" className="rounded-md border border-(--color-border) px-2.5 py-1.5 text-xs hover:bg-(--bg-key) focus-visible:outline-2 focus-visible:outline-(--color-accent)" onClick={restart}>
          {started ? t('Restart Tic-tac-toe') : t('Start Tic-tac-toe')}
        </button>
      </div>
      <p className="text-[11px] leading-relaxed text-(--color-text-muted)">{t('Use arrow keys to move between cells, then press Enter or Space to play.')}</p>
      <div role="group" aria-label={t('Tic-tac-toe board')} className="mx-auto grid w-full max-w-[15rem] grid-cols-3 gap-1.5">
        {state.board.map((mark, index) => (
          <button
            key={index}
            type="button"
            aria-label={mark ? t('Cell {0}: {1}', [index + 1, mark]) : t('Cell {0}', [index + 1])}
            aria-disabled={!active || !started || state.status !== 'playing' || mark !== null}
            tabIndex={index === focusedCell && started ? 0 : -1}
            ref={(element) => { cellRefs.current[index] = element }}
            onFocus={() => setFocusedCell(index)}
            onKeyDown={(event) => onCellKeyDown(event, index)}
            onClick={() => play(index)}
            className="aspect-square min-h-14 rounded-md border border-(--color-border) bg-(--bg-key) font-mono text-2xl font-semibold text-(--color-accent) hover:border-(--color-accent) focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-(--color-accent) focus-visible:outline-offset-1 aria-disabled:cursor-default"
          >
            {mark}
          </button>
        ))}
      </div>
      <p className="text-xs text-(--color-text-muted)">{t('Your move is answered by a local deterministic opponent.')}</p>
    </section>
  )
}
