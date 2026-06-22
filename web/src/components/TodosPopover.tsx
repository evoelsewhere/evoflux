/**
 * TodosPopover — task-list popover surfaced from the team-chat topbar.
 *
 * Renders the agent's task list as a flat, scrollable checklist (no
 * kanban columns, no priority badges). Each row is a status-aware
 * checkbox + content line:
 *
 *   - pending    → empty square
 *   - in_progress → empty square with a breathing pulse (animate-pulse)
 *   - completed  → checked square, content struck through + dimmed
 *   - cancelled  → empty square, content struck through + dimmed
 *
 * Sort order keeps the user's eye on what matters right now:
 *   in_progress → pending → completed → cancelled
 */

import { ListTodo, X } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { TopbarAction } from '@/components/ui/topbar-action'
import { TodosList } from './TodosList'
import type { TodoItem } from '@/api/types'

// ── Component ────────────────────────────────────────────────────────────────

interface TodosPopoverProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  todos: TodoItem[]
  /** When null/undefined the trigger is disabled (no active session). */
  sessionId: string | null
  /** Render the topbar trigger. Set false when another control opens this popover. */
  trigger?: boolean
}

export function TodosPopover({
  open,
  onOpenChange,
  todos,
  sessionId,
  trigger = true,
}: TodosPopoverProps) {
  const finishedCount = todos.filter(
    (t) => t.status === 'completed' || t.status === 'cancelled',
  ).length
  const hasInProgress = todos.some((t) => t.status === 'in_progress')
  const progressLabel =
    todos.length > 0 ? `${finishedCount}/${todos.length}` : undefined

  const content = (
    <TodosList
      todos={todos}
      listClassName="max-h-[min(60vh,24rem)]"
    />
  )

  if (!trigger) {
    if (!open) return null
    return (
      <div className="fixed inset-0 z-50" role="presentation">
        <button
          type="button"
          className="absolute inset-0 cursor-default bg-transparent"
          aria-label="Close tasks"
          onClick={() => onOpenChange(false)}
        />
        <section
          role="dialog"
          aria-label="Tasks"
          className="absolute right-2 top-[calc(var(--spacing-app-header)+env(safe-area-inset-top,0px)+0.5rem)] w-[min(calc(100vw-1rem),24rem)] overflow-hidden rounded-md bg-(--color-surface) p-0 shadow-md ring-1 ring-(--color-border)"
        >
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="absolute right-1.5 top-1.5 flex h-7 w-7 items-center justify-center rounded-md text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Close tasks"
          >
            <X size={14} aria-hidden="true" />
          </button>
          {content}
        </section>
      </div>
    )
  }

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      {trigger && (
        <PopoverTrigger
          render={
            <TopbarAction
              Icon={ListTodo}
              indicator={hasInProgress}
              badge={progressLabel}
              title={sessionId ? 'Task list (Ctrl+T)' : 'No active session'}
              aria-label="Task list"
            />
          }
          disabled={!sessionId}
        />
      )}
      <PopoverContent
        side="bottom"
        align="end"
        // ``ring-0`` cancels the shadcn default; outline comes from the
        // ``--color-border`` ring so the chrome matches Files / Agents.
        className="w-[min(calc(100vw-1rem),24rem)] overflow-hidden rounded-md bg-(--color-surface) p-0 shadow-md ring-1 ring-(--color-border)"
      >
        {content}
      </PopoverContent>
    </Popover>
  )
}
