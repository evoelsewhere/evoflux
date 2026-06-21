import { useEffect } from 'react'
import { useNavigate } from '@tanstack/react-router'

export function SchedulerPage() {
  const navigate = useNavigate()
  useEffect(() => { navigate({ to: '/forge', replace: true }) }, [navigate])
  return (
    <main className="mobile-safe-shell mobile-viewport flex h-dvh items-center justify-center bg-(--bg-page) text-(--color-text-muted)">
      <div className="flex items-center gap-3 rounded-full border border-(--color-border) bg-(--bg-card) px-4 py-3 text-sm shadow-sm">
        <span className="h-2 w-2 animate-pulse rounded-full bg-(--color-accent)" />
        Loading EvoFlux...
      </div>
    </main>
  )
}
