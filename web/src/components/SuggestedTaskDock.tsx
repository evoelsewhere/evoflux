/**
 * SuggestedTaskDock — open suggestion chips for the current session.
 *
 * Lives outside the transcript on purpose: a chip rendered only at the point
 * the agent raised it scrolls away within a few turns, which is exactly when
 * the user is least likely to have decided about it yet.
 */
import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'

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

  return (
    <section
      aria-label="Suggested tasks"
      className="mx-auto w-full max-w-3xl px-3 pb-2"
    >
      <button
        type="button"
        onClick={() => setCollapsed((value) => !value)}
        aria-expanded={!collapsed}
        className="mb-1.5 inline-flex items-center gap-1 text-[11px] font-medium text-(--color-text-subtle) transition-colors hover:text-(--color-text)"
      >
        {collapsed ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
        {tasks.length === 1 ? '1 suggested task' : `${tasks.length} suggested tasks`}
      </button>
      {!collapsed && (
        <div className="flex flex-col gap-1.5">
          {tasks.map((task) => (
            <SuggestedTaskCard key={task.id} task={task} />
          ))}
        </div>
      )}
    </section>
  )
}
