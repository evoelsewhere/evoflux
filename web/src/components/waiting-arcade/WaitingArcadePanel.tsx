import { lazy, Suspense, useState, type ComponentType, type LazyExoticComponent } from 'react'
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from '@/components/ui/popover'
import { useI18n } from '@/i18n'

type GameId = 'snake' | 'minesweeper' | 'tic-tac-toe' | '2048'
interface GameProps { active: boolean }

const gameComponents: Record<GameId, LazyExoticComponent<ComponentType<GameProps>>> = {
  snake: lazy(() => import('./games/SnakeGame').then(({ SnakeGame }) => ({ default: SnakeGame }))),
  minesweeper: lazy(() => import('./games/MinesweeperGame').then(({ MinesweeperGame }) => ({ default: MinesweeperGame }))),
  'tic-tac-toe': lazy(() => import('./games/TicTacToeGame').then(({ TicTacToeGame }) => ({ default: TicTacToeGame }))),
  '2048': lazy(() => import('./games/Game2048').then(({ Game2048 }) => ({ default: Game2048 }))),
}

const gameNames: Record<GameId, string> = {
  snake: 'Snake',
  minesweeper: 'Minesweeper Mini',
  'tic-tac-toe': 'Tic-tac-toe',
  '2048': '2048',
}

export interface WaitingArcadePanelProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  active: boolean
  launcherVisible: boolean
}

export function WaitingArcadePanel({ open, onOpenChange, active, launcherVisible }: WaitingArcadePanelProps) {
  const { t } = useI18n()
  const [selectedGame, setSelectedGame] = useState<GameId | null>(null)
  const SelectedGame = selectedGame ? gameComponents[selectedGame] : null

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger
        type="button"
        hidden={!launcherVisible}
        aria-label={t('Play while waiting')}
        title={t('Play while waiting')}
        className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-(--color-border) bg-(--bg-page) px-2.5 text-xs font-medium text-(--color-text-muted) transition-colors hover:border-(--color-border-strong) hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:outline-2 focus-visible:outline-(--color-accent)"
      >
        <span aria-hidden="true" className="font-mono text-(--color-accent)">▦</span>
        <span>{t('Play while waiting')}</span>
      </PopoverTrigger>
      <PopoverContent
        keepMounted
        side="top"
        align="end"
        sideOffset={8}
        collisionPadding={12}
        aria-label={t('Waiting Arcade')}
        className="max-h-[min(36rem,calc(100dvh-1.5rem))] w-[min(21rem,calc(100vw-1.5rem))] overflow-y-auto p-4"
      >
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
          <div className="grid gap-2" aria-label={t('Choose a game')}>
            {(['snake', 'minesweeper', 'tic-tac-toe', '2048'] as const).map((game) => (
              <button
                key={game}
                type="button"
                onClick={() => setSelectedGame(game)}
                className="flex min-h-12 items-center justify-between gap-3 rounded-md border border-(--color-border) bg-(--bg-page) px-3 text-left hover:border-(--color-accent)/60 hover:bg-(--bg-key) focus-visible:outline-2 focus-visible:outline-(--color-accent)"
              >
                <span className="text-sm font-medium">{t(gameNames[game])}</span>
                <span aria-hidden="true" className="font-mono text-sm text-(--color-accent)">↗</span>
              </button>
            ))}
          </div>
        )}
        <p className="mt-3 border-t border-(--color-border) pt-2 text-[11px] leading-relaxed text-(--color-text-muted)">
          {t('Local games only. Score does not represent agent progress.')}
        </p>
      </PopoverContent>
    </Popover>
  )
}
