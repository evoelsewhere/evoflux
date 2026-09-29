/**
 * SuggestedTaskDock — open suggestion chips for the current session.
 *
 * Lives outside the transcript on purpose: a chip rendered only at the point
 * the agent raised it scrolls away within a few turns, which is exactly when
 * the user is least likely to have decided about it yet.
 */
import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, Lightbulb } from 'lucide-react'

import { getSuggestedTasks } from '@/api/client'
import { SuggestedTaskCard } from '@/components/SuggestedTaskCard'
import { useTeamStore } from '@/stores/useTeamStore'

export function SuggestedTaskDock() {
  const sessionId = useTeamStore((state) => state.sessionId)
  const tasks = useTeamStore((state) => state.suggestedTasks)
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => {
    if (!sessionId) {
      useTeamStore.setState({ suggestedTasks: [] })
      return
    }
    let cancelled = false
    void getSuggestedTasks(sessionId)
      .then((rows) => {
        // A late response for a session the user already left would overwrite
        // the new session's chips with the old one's.
        if (cancelled || useTeamStore.getState().sessionId !== sessionId) return
        useTeamStore.setState({ suggestedTasks: rows })
      })
      .catch(() => {
        // Chips are additive; failing to list them must not break the chat.
      })
    return () => {
      cancelled = true
    }
  }, [sessionId])

  if (tasks.length === 0) return null

  // Floats in the main column's top-left corner, beside the centred
  // transcript, so it neither pushes the composer up nor reads as part of
  // the latest turn.
  return (
    <section
      aria-label="Suggested tasks"
      className="pointer-events-none absolute top-2 left-2 z-(--z-panel) flex w-[min(20rem,calc(100%-1rem))] flex-col items-start"
    >
      <button
        type="button"
        onClick={() => setCollapsed((value) => !value)}
        aria-expanded={!collapsed}
        className="pointer-events-auto inline-flex items-center gap-1.5 rounded-md border border-(--color-border-subtle) bg-(--bg-card) px-2 py-1 text-[11px] font-medium text-(--color-text-muted) shadow-sm transition-colors hover:text-(--color-text)"
      >
        <Lightbulb className="size-3 text-(--color-warning)" />
        {tasks.length === 1 ? '1 suggested task' : `${tasks.length} suggested tasks`}
        {collapsed ? <ChevronDown className="size-3" /> : <ChevronUp className="size-3" />}
      </button>
      {!collapsed && (
        <div className="pointer-events-auto mt-1.5 flex max-h-[min(60vh,32rem)] w-full flex-col gap-1.5 overflow-y-auto">
          {tasks.map((task) => (
            <SuggestedTaskCard key={task.id} task={task} className="bg-(--bg-card) shadow-md" />
          ))}
        </div>
      )}
    </section>
  )
}
