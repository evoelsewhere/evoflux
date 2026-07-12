/**
 * FloatingTodosPanel — floating task list in the top-right corner.
 *
 * A toggleable panel that shows the task list. Can be minimized to just
 * a floating button with task count badge.
 */

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { CheckSquare, X, Minimize2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { TodosList } from './TodosList'
import type { TodoItem } from '@/api/types'

export interface FloatingTodosPanelProps {
  todos?: TodoItem[]
  className?: string
}

export function FloatingTodosPanel({ todos, className }: FloatingTodosPanelProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [isMinimized, setIsMinimized] = useState(false)

  const todoCount = todos?.length ?? 0
  const finishedCount = todos?.filter(
    (t) => t.status === 'completed' || t.status === 'cancelled',
  ).length ?? 0
  const pendingCount = todoCount - finishedCount

  // Don't render if no todos
  if (todoCount === 0) return null

  return (
    <div className={cn('fixed right-4 top-4 z-50', className)}>
      <AnimatePresence mode="wait">
        {!isOpen ? (
          /* Floating toggle button */
          <motion.button
            key="toggle"
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.8, opacity: 0 }}
            transition={{ duration: 0.15 }}
            type="button"
            onClick={() => setIsOpen(true)}
            className={cn(
              'flex h-10 items-center gap-2 rounded-lg border border-(--color-border)',
              'bg-(--bg-card) px-3 shadow-lg transition-colors',
              'hover:border-(--color-accent)/40 hover:bg-(--bg-key)',
            )}
            title={`Tasks (${finishedCount}/${todoCount} done)`}
          >
            <CheckSquare size={16} className="text-(--color-accent)" />
            {pendingCount > 0 && (
              <span className="font-mono text-xs font-medium text-(--color-text-muted)">
                {pendingCount}
              </span>
            )}
          </motion.button>
        ) : isMinimized ? (
          /* Minimized: just the button with count */
          <motion.button
            key="minimized"
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.8, opacity: 0 }}
            transition={{ duration: 0.15 }}
            type="button"
            onClick={() => setIsMinimized(false)}
            className={cn(
              'flex h-10 items-center gap-2 rounded-lg border border-(--color-border)',
              'bg-(--bg-card) px-3 shadow-lg transition-colors',
              'hover:border-(--color-accent)/40 hover:bg-(--bg-key)',
            )}
            title={`Tasks (${finishedCount}/${todoCount} done) — click to expand`}
          >
            <CheckSquare size={16} className="text-(--color-accent)" />
            <span className="font-mono text-xs font-medium text-(--color-text-muted)">
              {finishedCount}/{todoCount}
            </span>
          </motion.button>
        ) : (
          /* Full panel */
          <motion.div
            key="panel"
            initial={{ scale: 0.95, opacity: 0, y: -10 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.95, opacity: 0, y: -10 }}
            transition={{ duration: 0.15 }}
            className={cn(
              'w-80 rounded-lg border border-(--color-border)',
              'bg-(--bg-card) shadow-xl',
            )}
          >
            {/* Header with controls */}
            <div className="flex items-center justify-between border-b border-(--color-border) px-3 py-2">
              <div className="flex items-center gap-2">
                <CheckSquare size={14} className="text-(--color-accent)" />
                <span className="font-mono text-xs font-medium uppercase tracking-wider text-(--color-text-muted)">
                  Tasks
                </span>
                {todoCount > 0 && (
                  <span className="font-mono text-xs text-(--color-text-subtle)">
                    {finishedCount}/{todoCount}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setIsMinimized(true)}
                  className="flex h-6 w-6 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-hover) hover:text-(--color-text)"
                  title="Minimize"
                >
                  <Minimize2 size={12} />
                </button>
                <button
                  type="button"
                  onClick={() => setIsOpen(false)}
                  className="flex h-6 w-6 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-hover) hover:text-(--color-text)"
                  title="Close"
                >
                  <X size={12} />
                </button>
              </div>
            </div>

            {/* Task list */}
            <TodosList
              todos={todos ?? []}
              listClassName="max-h-[min(50vh,20rem)]"
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
