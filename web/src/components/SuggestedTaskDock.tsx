/**
 * SuggestedTaskDock — open suggestion chips for the current session.
 *
 * Lives outside the transcript on purpose: a chip rendered only at the point
 * the agent raised it scrolls away within a few turns, which is exactly when
 * the user is least likely to have decided about it yet.
 *
 * Rendered as a control in the workbench bar's right-hand cluster: floating
 * over the transcript's top-left corner covered the first lines of the chat.
 * It renders nothing (not even its divider) while there are no suggestions.
 */
import { useEffect, useState } from 'react'
import { ChevronDown, Lightbulb } from 'lucide-react'

import { getSuggestedTasks } from '@/api/client'
import { SuggestedTaskCard } from '@/components/SuggestedTaskCard'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useTeamStore } from '@/stores/useTeamStore'

export function SuggestedTaskDock() {
  const sessionId = useTeamStore((state) => state.sessionId)
  const tasks = useTeamStore((state) => state.suggestedTasks)
  const [open, setOpen] = useState(false)

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

  // Close once the last chip is dealt with, so the next suggestion doesn't pop
  // the list open by itself. Adjusted during render rather than in an effect.
  const [hadTasks, setHadTasks] = useState(tasks.length > 0)
  if (hadTasks !== tasks.length > 0) {
    setHadTasks(tasks.length > 0)
    if (tasks.length === 0) setOpen(false)
  }

  if (tasks.length === 0) return null

  const label = tasks.length === 1 ? '1 suggested task' : `${tasks.length} suggested tasks`

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger
          render={
            <button
              type="button"
              aria-label={label}
              title={label}
              className="group flex h-7 items-center gap-1.5 rounded-lg px-2 text-xs font-medium text-(--color-text-muted) outline-none transition-colors hover:bg-(--bg-key) hover:text-(--color-text) data-[popup-open]:bg-(--bg-key) data-[popup-open]:text-(--color-text)"
            />
          }
        >
          <Lightbulb size={14} className="shrink-0 text-(--color-warning)" aria-hidden="true" />
          <span className="tabular-nums">{tasks.length}</span>
          <ChevronDown
            size={11}
            className="text-(--color-text-subtle) transition-transform group-data-[popup-open]:rotate-180"
            aria-hidden="true"
          />
        </PopoverTrigger>
        <PopoverContent
          align="end"
          className="w-[min(22rem,calc(100vw-1rem))] gap-0 overflow-hidden border-(--color-border) bg-(--color-surface) p-0 shadow-xl"
        >
          <section aria-label="Suggested tasks" className="flex flex-col">
            <p className="border-b border-(--color-border-subtle) px-3 py-2 text-xs font-medium text-(--color-text-muted)">
              {label}
            </p>
            <div className="flex max-h-[min(60vh,32rem)] flex-col gap-1.5 overflow-y-auto p-2">
              {tasks.map((task) => (
                <SuggestedTaskCard key={task.id} task={task} className="bg-(--bg-card)" />
              ))}
            </div>
          </section>
        </PopoverContent>
      </Popover>
      <span className="mx-0.5 h-4 w-px bg-(--color-border)" aria-hidden="true" />
    </>
  )
}
