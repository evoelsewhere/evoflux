/**
 * TaskProgressPill — live working-time + chapter progress indicator.
 *
 * Shown in the chat header while the agent is working. Displays:
 *   ⏱ 4m 32s  ·  Step 3 / 7: Writing unit tests
 *
 * Disappears when the agent is idle. Only appears after the agent has
 * been working for > SHOW_AFTER_MS ms so it doesn't flash for quick replies.
 */

import { useState, useEffect, useRef } from 'react'
import { Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Chapter } from '@/api/types'

const SHOW_AFTER_MS = 8_000   // show pill after 8s of work
const TICK_MS = 1_000

function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rem = s % 60
  return rem > 0 ? `${m}m ${rem}s` : `${m}m`
}

export interface TaskProgressPillProps {
  isWorking: boolean
  chapters?: Chapter[]
  className?: string
}

export function TaskProgressPill({ isWorking, chapters = [], className }: TaskProgressPillProps) {
  const startRef = useRef<number | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [visible, setVisible] = useState(false)

  // Track when the agent starts/stops working
  useEffect(() => {
    if (isWorking) {
      if (!startRef.current) {
        startRef.current = Date.now()
        setElapsed(0) // eslint-disable-line react-hooks/set-state-in-effect
      }
    } else {
      startRef.current = null
      setVisible(false)
      setElapsed(0)
    }
  }, [isWorking])

  // Tick the elapsed time every second
  useEffect(() => {
    if (!isWorking) return
    const id = setInterval(() => {
      if (!startRef.current) return
      const ms = Date.now() - startRef.current
      setElapsed(ms)
      if (ms >= SHOW_AFTER_MS) setVisible(true)
    }, TICK_MS)
    return () => clearInterval(id)
  }, [isWorking])

  if (!visible || !isWorking) return null

  const latestChapter = chapters.at(-1)
  // Chapters accumulate as the agent works, so `total` is the CURRENT step
  // number, not a known target — showing "N/N" falsely implied completion.
  const currentStep = chapters.length

  return (
    <div
      className={cn(
        'flex items-center gap-1.5 rounded-md px-2 py-1',
        'border border-(--color-border) bg-(--bg-subtle)',
        'text-xs text-(--color-text-muted)',
        'animate-in fade-in-0 slide-in-from-top-1 duration-300',
        className,
      )}
      title={latestChapter ? `Current step: ${latestChapter.title}` : undefined}
    >
      <Clock size={11} className="shrink-0 text-amber-400" aria-hidden="true" />

      <span className="tabular-nums font-mono">{formatElapsed(elapsed)}</span>

      {latestChapter && (
        <>
          <span className="text-(--border-subtle) select-none">·</span>
          {currentStep > 1 && (
            <span className="tabular-nums">
              Step {currentStep}
            </span>
          )}
          {currentStep > 1 && (
            <span className="text-(--border-subtle) select-none">·</span>
          )}
          <span className="max-w-[160px] truncate">
            {latestChapter.title}
          </span>
        </>
      )}
    </div>
  )
}
