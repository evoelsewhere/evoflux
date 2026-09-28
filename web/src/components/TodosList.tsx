import { motion } from 'framer-motion'
import { Circle, CircleCheck, CircleMinus, LoaderCircle, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { fadeRise, staggerDelay, useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'
import { TierBadge } from './TierBadge'
import type { TodoItem, TodoTier } from '@/api/types'

const STATUS_ICON: Record<TodoItem['status'], LucideIcon> = {
  completed: CircleCheck,
  cancelled: CircleMinus,
  in_progress: LoaderCircle,
  pending: Circle,
}

const STATUS_ICON_COLOR: Record<TodoItem['status'], string> = {
  completed: 'text-(--color-success)',
  cancelled: 'text-(--color-text-subtle)',
  in_progress: 'text-(--color-info) animate-spin',
  pending: 'text-(--color-text-subtle)',
}

const STATUS_ORDER: Record<TodoItem['status'], number> = {
  in_progress: 0,
  pending: 1,
  completed: 2,
  cancelled: 3,
}

const TIER_TEXT: Record<TodoTier, string> = {
  trivial: 'trivial',
  simple: 'simple',
  multi_step: 'multi-step',
  complex: 'complex',
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
  compact?: boolean
  onClose?: () => void
}

export function TodosList({
  todos,
  className,
  headerClassName,
  listClassName,
  emptyClassName,
  compact = false,
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
          'flex items-center justify-between gap-3 px-3 pb-1 pt-2.5',
          headerClassName,
        )}
      >
        <span className="text-xs font-medium text-(--color-text)">Tasks</span>
        <div className="flex items-center gap-2">
          {todos.length > 0 && (
            <span className="text-[11px] tabular-nums text-(--color-text-muted)">
              {finishedCount} of {todos.length} done
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
            'px-3 py-6 text-center text-xs text-(--color-text-subtle)',
            emptyClassName,
          )}
        >
          No tasks yet
        </p>
      ) : (
        <ul
          aria-label="Task list"
          className={cn(
            'scrollbar-none max-h-[min(60vh,24rem)] overflow-y-auto pb-1.5',
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
                className={cn(
                  'flex items-start gap-2 px-3',
                  compact ? 'py-1.5' : 'py-2',
                )}
              >
                <Icon
                  size={14}
                  aria-hidden="true"
                  className={cn('mt-px shrink-0', STATUS_ICON_COLOR[todo.status])}
                />
                <span
                  className={cn(
                    'min-w-0 flex-1 text-xs leading-snug',
                    isStruck
                      ? 'text-(--color-text-subtle) line-through'
                      : isInProgress
                        ? 'font-medium text-(--color-text)'
                        : 'text-(--color-text-2)',
                  )}
                >
                  {todo.content}
                </span>
                {todo.tier && !isStruck && (
                  compact ? (
                    // A tinted mono badge per row outweighed the task text in
                    // the composer's small list; the tier reads as a note.
                    <span
                      className="mt-px shrink-0 text-[10px] text-(--color-text-subtle)"
                      title={`Tool access tier: ${TIER_TEXT[todo.tier]}`}
                    >
                      {TIER_TEXT[todo.tier]}
                    </span>
                  ) : (
                    <TierBadge tier={todo.tier} className="mt-0.5" />
                  )
                )}
                {agent && (
                  <span
                    className={cn(
                      'shrink-0 truncate text-(--color-text-subtle)',
                      compact ? 'mt-px max-w-20 text-[10px]' : 'mt-0.5 text-xs',
                    )}
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
