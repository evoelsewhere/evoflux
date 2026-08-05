import { useEffect, useState } from 'react'

import { ActivityStatus } from '@/components/motion/ActivityStatus'

function formatElapsed(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000))
  if (totalSeconds < 1) return 'Working'
  if (totalSeconds < 60) return `Working for ${totalSeconds}s`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `Working for ${minutes}m ${seconds}s`
}

/** A stable turn-level clock, isolated so the transcript does not tick. */
export function StreamingTurnHeader({ startedAt }: { startedAt?: number }) {
  const [mountedAt] = useState(() => Date.now())
  const start = startedAt ?? mountedAt
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1_000)
    return () => window.clearInterval(interval)
  }, [])

  return (
    <div className="mb-3 flex items-center gap-3" aria-label={formatElapsed(now - start)}>
      <ActivityStatus
        label={formatElapsed(now - start)}
        className="shrink-0 text-xs font-normal"
      />
      <span className="h-px min-w-8 flex-1 bg-(--color-border-subtle)" aria-hidden="true" />
    </div>
  )
}
