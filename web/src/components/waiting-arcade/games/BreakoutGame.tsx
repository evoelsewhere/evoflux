import { useEffect, useRef, useState } from 'react'
import { useI18n } from '@/i18n'
import { advanceBreakout, createBreakoutState, moveBreakoutPaddle, startBreakout } from './breakout-logic'

interface BreakoutGameProps { active: boolean }
export function BreakoutGame({ active }: BreakoutGameProps) {
  const { t } = useI18n()
  const [state, setState] = useState(() => createBreakoutState())
  const [reducedMotion, setReducedMotion] = useState(() => (
    typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  ))
  const [documentVisible, setDocumentVisible] = useState(() => document.visibilityState !== 'hidden')
  const boardRef = useRef<HTMLDivElement>(null)
  const interval = state.status === 'playing' ? reducedMotion ? 64 : 32 : null

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)')
    const updatePreference = (event: MediaQueryListEvent) => setReducedMotion(event.matches)
    preference.addEventListener('change', updatePreference)
    return () => preference.removeEventListener('change', updatePreference)
  }, [])

  useEffect(() => {
    const updateVisibility = () => setDocumentVisible(document.visibilityState !== 'hidden')
    document.addEventListener('visibilitychange', updateVisibility)
    return () => document.removeEventListener('visibilitychange', updateVisibility)
  }, [])

  useEffect(() => {
    if (!active || !documentVisible || interval === null) return
    const timer = window.setInterval(() => setState((current) => advanceBreakout(current)), interval)
    return () => window.clearInterval(timer)
  }, [active, documentVisible, interval])

  const launch = () => { setState((current) => startBreakout(current)); boardRef.current?.focus() }
  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!active) return
    if (event.key === 'ArrowLeft' || event.key.toLowerCase() === 'a') { event.preventDefault(); setState((current) => moveBreakoutPaddle(current, -7)) }
    else if (event.key === 'ArrowRight' || event.key.toLowerCase() === 'd') { event.preventDefault(); setState((current) => moveBreakoutPaddle(current, 7)) }
    else if (event.key === ' ' && !event.repeat) { event.preventDefault(); if (state.status === 'playing') setState((current) => ({ ...current, status: 'paused' })); else launch() }
  }

  const message = state.status === 'won' ? t('Board cleared — you win') : state.status === 'lost' ? t('Breakout over — restart to play again') : state.status === 'paused' ? t('Paused — press Space or Resume') : t('Use left/right arrows or A/D; Space to launch or pause.')
  return (
    <section className="flex flex-col gap-3" aria-label={t('Mini Breakout game')}>
      <div className="flex items-center justify-between gap-3 font-mono text-xs text-(--color-text-muted)"><span>{t('Score')}: {state.score}</span><span>{t('Lives')}: {state.lives}</span></div>
      <div ref={boardRef} role="group" aria-label={t('Mini Breakout board')} tabIndex={0} onKeyDown={onKeyDown} className="waiting-breakout-board relative mx-auto aspect-[8/5] w-full max-w-[20rem] overflow-hidden rounded-md border border-(--color-border) bg-(--bg-key) outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent)/60">
        {state.bricks.map((brick) => <span key={brick.id} className="waiting-breakout-brick absolute h-[4%] rounded-[2px] bg-(--color-accent)/75" style={{ left: `${brick.x}%`, top: `${brick.y}%`, width: '9%' }} />)}
        <span data-testid="breakout-ball" className="absolute size-[3.5%] rounded-[2px] bg-(--color-text) transition-[left,top] duration-75 motion-reduce:transition-none" style={{ left: `${state.ballX}%`, top: `${state.ballY}%` }} />
        <span data-testid="breakout-paddle" className="absolute h-[3%] rounded-sm bg-(--color-accent) transition-[left] duration-75 motion-reduce:transition-none" style={{ left: `${state.paddleX}%`, bottom: '5%', width: '18%', transform: 'translateX(-50%)' }} />
        {state.status !== 'playing' && <span className="absolute inset-0 grid place-items-center bg-(--bg-page)/65 px-4 text-center text-xs text-(--color-text-muted)">{state.status === 'ready' ? t('Ready — press Space or Start') : message}</span>}
      </div>
      <div className="flex justify-center gap-2">
        {state.status === 'ready' && <button type="button" onClick={launch} className="rounded-md border border-(--color-border) px-2.5 py-1.5 text-xs hover:bg-(--bg-key) focus-visible:outline-2 focus-visible:outline-(--color-accent)">{t('Start Breakout')}</button>}
        {state.status === 'playing' && <button type="button" onClick={() => setState((current) => ({ ...current, status: 'paused' }))} className="rounded-md border border-(--color-border) px-2.5 py-1.5 text-xs hover:bg-(--bg-key) focus-visible:outline-2 focus-visible:outline-(--color-accent)">{t('Pause Breakout')}</button>}
        {state.status === 'paused' && <button type="button" onClick={launch} className="rounded-md border border-(--color-border) px-2.5 py-1.5 text-xs hover:bg-(--bg-key) focus-visible:outline-2 focus-visible:outline-(--color-accent)">{t('Resume')}</button>}
        {(state.status === 'won' || state.status === 'lost') && <button type="button" onClick={() => { setState(createBreakoutState()); boardRef.current?.focus() }} className="rounded-md border border-(--color-border) px-2.5 py-1.5 text-xs hover:bg-(--bg-key) focus-visible:outline-2 focus-visible:outline-(--color-accent)">{t('Restart Breakout')}</button>}
      </div>
      <p aria-live="polite" className="text-center text-xs text-(--color-text-muted)">{message}</p>
    </section>
  )
}
