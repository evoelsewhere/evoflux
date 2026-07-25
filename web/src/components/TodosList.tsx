import { motion } from 'framer-motion'
import { Square, SquareCheck, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { fadeRise, staggerDelay, useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'
import { TierBadge } from './TierBadge'
import type { TodoItem } from '@/api/types'

const STATUS_ICON: Record<TodoItem['status'], LucideIcon> = {
  completed: SquareCheck,
  cancelled: Square,
  in_progress: Square,
  pending: Square,
}

const STATUS_ICON_COLOR: Record<TodoItem['status'], string> = {
  completed: 'text-(--color-success)',
  cancelled: 'text-(--color-text-subtle)',
  in_progress: 'text-(--color-info)',
  pending: 'text-(--color-text-muted)',
}

const STATUS_ORDER: Record<TodoItem['status'], number> = {
  in_progress: 0,
  pending: 1,
  completed: 2,
  cancelled: 3,
}

function getAgentLabel(todo: TodoItem): string | null {
  return todo.claimed_by ?? todo.assigned_to ?? null
}

export interface TodosListProps {
  todos: TodoItem[]
  className?: string
  headerClassName?: string
  listClassName?: string
  emptyClassName?: string
  onClose?: () => void
}

export function TodosList({
  todos,
  className,
  headerClassName,
  listClassName,
  emptyClassName,
  onClose,
}: TodosListProps) {
  const preset = useMotionPreset()
  const enter = fadeRise(preset, 4)
  const finishedCount = todos.filter(
    (t) => t.status === 'completed' || t.status === 'cancelled',
  ).length
  const sortedTodos = [...todos].sort(
    (a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status],
  )

  return (
    <div className={className}>
      <div
        className={cn(
          'flex items-center justify-between border-b border-(--color-border) px-3 py-2',
          headerClassName,
        )}
      >
        <span className="font-mono text-xs font-medium uppercase tracking-wider text-(--color-text-muted)">
          Tasks
        </span>
        <div className="flex items-center gap-2">
          {todos.length > 0 && (
            <span className="font-mono text-xs text-(--color-text-subtle)">
              {finishedCount}/{todos.length} done
            </span>
          )}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Dismiss tasks"
              className="flex h-5 w-5 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            >
              <X size={12} aria-hidden="true" />
            </button>
          )}
        </div>
      </div>

      {todos.length === 0 ? (
        <p
          role="status"
          className={cn(
            'px-3 py-6 text-center font-(family-name:--font-hand) text-sm text-(--color-text-subtle)',
            emptyClassName,
          )}
        >
          No tasks yet
        </p>
      ) : (
        <ul
          aria-label="Task list"
          className={cn(
            'scrollbar-none max-h-[min(60vh,24rem)] overflow-y-auto py-1',
            listClassName,
          )}
        >
          {sortedTodos.map((todo, index) => {
            const Icon = STATUS_ICON[todo.status]
            const isStruck =
              todo.status === 'completed' || todo.status === 'cancelled'
            const isInProgress = todo.status === 'in_progress'
            const agent = getAgentLabel(todo)
            return (
              <motion.li
                key={todo.task_id}
                initial={enter.initial}
                animate={enter.animate}
                transition={{ ...enter.transition, delay: staggerDelay(preset, index) }}
                className="flex items-start gap-2.5 px-3 py-1.5"
              >
                <Icon
                  size={14}
                  aria-hidden="true"
                  className={`mt-0.5 shrink-0 ${STATUS_ICON_COLOR[todo.status]} ${
                    isInProgress ? 'animate-pulse' : ''
                  }`}
                />
                <span
                  className={`min-w-0 flex-1 text-xs leading-snug ${
                    isStruck
                      ? 'text-(--color-text-subtle) line-through'
                      : 'text-(--color-text)'
                  }`}
                >
                  {todo.content}
                </span>
                {todo.tier && !isStruck && (
                  <TierBadge tier={todo.tier} className="mt-0.5" />
                )}
                {agent && (
                  <span
                    className="mt-0.5 shrink-0 font-mono text-xs uppercase tracking-wide text-(--color-text-subtle)"
                    title={`Assigned to ${agent}`}
                  >
                    {agent}
                  </span>
                )}
              </motion.li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
