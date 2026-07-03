import { useEffect } from 'react'
import { useNavigate } from '@tanstack/react-router'
import EvoFluxLogo from '@/assets/brand/evoflux-app-icon.png'

export function SchedulerPage() {
  const navigate = useNavigate()
  useEffect(() => { navigate({ to: '/', replace: true }) }, [navigate])
  return (
    <main className="mobile-safe-shell mobile-viewport flex h-dvh items-center justify-center bg-(--bg-page)" aria-label="Loading EvoFlux">
      <div className="relative flex items-center justify-center">
        <div className="absolute h-20 w-20 animate-pulse rounded-3xl bg-(--color-accent) opacity-20 blur-xl motion-reduce:animate-none" />
        <img src={EvoFluxLogo} width={52} height={52} className="relative rounded-2xl" alt="" aria-hidden="true" />
      </div>
    </main>
  )
}
