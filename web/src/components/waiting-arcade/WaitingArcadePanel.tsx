import { lazy, Suspense, useId, useState, type ComponentType, type LazyExoticComponent } from 'react'
import { Gamepad2, MoreHorizontal } from 'lucide-react'
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTrigger,
  PopoverTitle,
} from '@/components/ui/popover'
import { useI18n } from '@/i18n'

type GameId = 'snake' | 'minesweeper' | 'tic-tac-toe' | '2048' | 'memory' | 'breakout'
interface GameProps { active: boolean }

const gameComponents: Record<GameId, LazyExoticComponent<ComponentType<GameProps>>> = {
  snake: lazy(() => import('./games/SnakeGame').then(({ SnakeGame }) => ({ default: SnakeGame }))),
  minesweeper: lazy(() => import('./games/MinesweeperGame').then(({ MinesweeperGame }) => ({ default: MinesweeperGame }))),
  'tic-tac-toe': lazy(() => import('./games/TicTacToeGame').then(({ TicTacToeGame }) => ({ default: TicTacToeGame }))),
  '2048': lazy(() => import('./games/Game2048').then(({ Game2048 }) => ({ default: Game2048 }))),
  memory: lazy(() => import('./games/MemoryGame').then(({ MemoryGame }) => ({ default: MemoryGame }))),
  breakout: lazy(() => import('./games/BreakoutGame').then(({ BreakoutGame }) => ({ default: BreakoutGame }))),
}

const gameNames: Record<GameId, string> = {
  snake: 'Snake',
  minesweeper: 'Minesweeper Mini',
  'tic-tac-toe': 'Tic-tac-toe',
  '2048': '2048',
  memory: 'Memory Pairs',
  breakout: 'Mini Breakout',
}

function GameGlyph({ game }: { game: GameId }) {
  const common = { fill: 'currentColor', shapeRendering: 'crispEdges' as const }
  return <svg aria-hidden="true" viewBox="0 0 16 16" className="size-5 shrink-0 text-(--color-accent)" {...common}>
    {game === 'snake' && <><path d="M2 3h4v3H3v4h5v3H2zM8 7h5v3H8zM11 4h3v3h-3z" /><path d="M12 5h1v1h-1z" fill="var(--bg-page)" /></>}
    {game === 'minesweeper' && <><path d="M6 1h4v2h3v3h2v4h-2v3h-3v2H6v-2H3v-3H1V6h2V3h3z" /><path d="M6 5h4v6H6z" fill="var(--bg-page)" /></>}
    {game === 'tic-tac-toe' && <path d="M5 2h2v4H5zM10 2h2v4h-2zM5 10h2v4H5zM10 10h2v4h-2zM2 5h4v2H2zM10 5h4v2h-4zM2 10h4v2H2zM10 10h4v2h-4z" />}
    {game === '2048' && <><path d="M2 2h5v5H2zM9 2h5v5H9zM2 9h5v5H2zM9 9h5v5H9z" /><path d="M4 4h1v1H4zM11 4h1v1h-1zM4 11h1v1H4z" fill="var(--bg-page)" /></>}
    {game === 'memory' && <><path d="M1 3h6v10H1zM9 3h6v10H9z" /><path d="M3 5h2v2H3zM11 9h2v2h-2z" fill="var(--bg-page)" /></>}
    {game === 'breakout' && <path d="M1 2h4v2H1zM6 2h4v2H6zM11 2h4v2h-4zM3 5h4v2H3zM8 5h4v2H8zM7 9h2v2H7zM5 13h6v2H5z" />}
  </svg>
}

export interface WaitingArcadePanelProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  active: boolean
  launcherVisible: boolean
  launcherEmphasized?: boolean
}

export function WaitingArcadePanel({ open, onOpenChange, active, launcherVisible, launcherEmphasized = false }: WaitingArcadePanelProps) {
  const { t } = useI18n()
  const [selectedGame, setSelectedGame] = useState<GameId | null>(null)
  const [launcherMenuOpen, setLauncherMenuOpen] = useState(false)
  const triggerId = useId()
  const SelectedGame = selectedGame ? gameComponents[selectedGame] : null
  const handleOpenChange = (nextOpen: boolean) => {
    setLauncherMenuOpen(nextOpen && !launcherEmphasized)
    onOpenChange(nextOpen)
  }

  return (
    <>
      <Popover open={open} onOpenChange={handleOpenChange} triggerId={triggerId}>
        {launcherVisible && (
          <PopoverTrigger
            id={triggerId}
            type="button"
            aria-label={t(launcherEmphasized ? 'Play while waiting' : 'More composer actions')}
            title={t(launcherEmphasized ? 'Play while waiting' : 'More composer actions')}
            className={launcherEmphasized
              ? 'inline-flex h-8 max-w-[min(12rem,45vw)] shrink-0 items-center justify-center gap-1.5 rounded-md border border-(--color-accent)/40 bg-(--color-accent)/10 px-2.5 text-xs font-medium text-(--color-text) transition-colors hover:border-(--color-accent) hover:bg-(--color-accent)/15 focus-visible:outline-2 focus-visible:outline-(--color-accent)'
              : 'inline-flex size-8 shrink-0 items-center justify-center rounded-md border border-transparent text-(--color-text-muted) transition-colors hover:border-(--color-border) hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:outline-2 focus-visible:outline-(--color-accent)'}
          >
            {launcherEmphasized ? (
              <>
                <Gamepad2 size={15} className="text-(--color-accent)" aria-hidden="true" />
                <span className="truncate">{t('Play while waiting')}</span>
              </>
            ) : <MoreHorizontal size={16} aria-hidden="true" />}
          </PopoverTrigger>
        )}
      <PopoverContent
        keepMounted
        side="top"
        align="end"
        sideOffset={8}
        collisionPadding={12}
        aria-label={t(launcherMenuOpen ? 'More composer actions' : 'Waiting Arcade')}
        className="max-h-[min(36rem,calc(100dvh-1.5rem))] w-[min(21rem,calc(100vw-1.5rem))] overflow-y-auto p-4"
      >
        {launcherMenuOpen ? (
          <button
            type="button"
            onClick={() => setLauncherMenuOpen(false)}
            className="flex min-h-9 w-full items-center gap-2 rounded-md px-2 text-left text-sm transition-colors hover:bg-(--bg-key) focus-visible:outline-2 focus-visible:outline-(--color-accent)"
          >
            <Gamepad2 className="text-(--color-accent)" aria-hidden="true" />
            {t('Play while waiting')}
          </button>
        ) : <>
        <PopoverHeader className="mb-2">
          <div className="flex items-start justify-between gap-3">
            <div>
              <PopoverTitle>{t('Waiting Arcade')}</PopoverTitle>
              <PopoverDescription>{t('A small local game while your agent works.')}</PopoverDescription>
            </div>
            <button type="button" aria-label={t('Close game')} onClick={() => onOpenChange(false)} className="rounded-md px-2 py-1 text-xs text-(--color-text-muted) hover:bg-(--bg-key) focus-visible:outline-2 focus-visible:outline-(--color-accent)">
              {t('Close')}
            </button>
          </div>
        </PopoverHeader>

        {SelectedGame ? (
          <div className="flex flex-col gap-3">
            <button type="button" onClick={() => setSelectedGame(null)} className="self-start rounded px-1 py-0.5 text-xs text-(--color-text-muted) hover:text-(--color-text) focus-visible:outline-2 focus-visible:outline-(--color-accent)">
              ← {t('Choose another game')}
            </button>
            <Suspense fallback={<p className="py-8 text-center text-xs text-(--color-text-muted)">{t('Loading game…')}</p>}>
              <SelectedGame active={active && open} />
            </Suspense>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-2" aria-label={t('Choose a game')}>
            {(['snake', 'minesweeper', 'tic-tac-toe', '2048', 'memory', 'breakout'] as const).map((game) => (
              <button
                key={game}
                type="button"
                onClick={() => setSelectedGame(game)}
                className="flex min-h-[4.5rem] items-center justify-between gap-2 rounded-md border border-(--color-border) bg-(--bg-page) px-3 text-left transition-[border-color,background-color,transform] duration-150 hover:-translate-y-0.5 hover:border-(--color-accent)/60 hover:bg-(--bg-key) active:translate-y-0 motion-reduce:transform-none motion-reduce:transition-none focus-visible:outline-2 focus-visible:outline-(--color-accent)"
              >
                <span className="min-w-0 text-sm font-medium leading-tight">{t(gameNames[game])}</span>
                <GameGlyph game={game} />
              </button>
            ))}
          </div>
        )}
        <p className="mt-3 border-t border-(--color-border) pt-2 text-[11px] leading-relaxed text-(--color-text-muted)">
          {t('Local games only. Score does not represent agent progress.')}
        </p>
        </>}
      </PopoverContent>
      </Popover>
    </>
  )
}
