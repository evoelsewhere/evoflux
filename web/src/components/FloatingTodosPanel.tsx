/**
 * FloatingTodosPanel — floating task list that can be dragged anywhere.
 *
 * A draggable, toggleable panel that shows the task list. Can be minimized
 * to just a floating button with task count badge.
 */

import { useState, useRef } from 'react'
import { motion, AnimatePresence, type PanInfo } from 'framer-motion'
import { CheckSquare, X, Minimize2, GripVertical } from 'lucide-react'
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
  const [position, setPosition] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)
  const constraintsRef = useRef<HTMLDivElement>(null)

  const todoCount = todos?.length ?? 0
  const finishedCount = todos?.filter(
    (t) => t.status === 'completed' || t.status === 'cancelled',
  ).length ?? 0
  const pendingCount = todoCount - finishedCount

  // Don't render if no todos
  if (todoCount === 0) return null

  const handleDragEnd = (_: never, info: PanInfo) => {
    setIsDragging(false)
    setPosition({
      x: position.x + info.offset.x,
      y: position.y + info.offset.y,
    })
  }

  const handleDragStart = () => {
    setIsDragging(true)
  }

  return (
    <>
      {/* Drag constraints - full viewport */}
      <div ref={constraintsRef} className="fixed inset-0 z-40 pointer-events-none" />

      <motion.div
        className={cn('fixed z-50', className)}
        style={{
          right: position.x === 0 ? 16 : undefined,
          left: position.x !== 0 ? `calc(50% + ${position.x}px)` : undefined,
          top: position.y === 0 ? 48 : `calc(50% + ${position.y}px)`,
        }}
        drag
        dragConstraints={constraintsRef}
        dragElastic={0.1}
        dragMomentum={false}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
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
              onClick={() => !isDragging && setIsOpen(true)}
              className={cn(
                'flex h-10 items-center gap-2 rounded-lg border border-(--color-border)',
                'bg-(--bg-card) px-3 shadow-lg transition-colors cursor-grab active:cursor-grabbing',
                'hover:border-(--color-accent)/40 hover:bg-(--bg-key)',
              )}
              title={`Tasks (${finishedCount}/${todoCount} done) — drag to move`}
            >
              <GripVertical size={12} className="text-(--color-text-subtle)" />
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
              onClick={() => !isDragging && setIsMinimized(false)}
              className={cn(
                'flex h-10 items-center gap-2 rounded-lg border border-(--color-border)',
                'bg-(--bg-card) px-3 shadow-lg transition-colors cursor-grab active:cursor-grabbing',
                'hover:border-(--color-accent)/40 hover:bg-(--bg-key)',
              )}
              title={`Tasks (${finishedCount}/${todoCount} done) — click to expand, drag to move`}
            >
              <GripVertical size={12} className="text-(--color-text-subtle)" />
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
              {/* Header with drag handle and controls */}
              <div
                className={cn(
                  'flex items-center justify-between border-b border-(--color-border) px-3 py-2',
                  'cursor-grab active:cursor-grabbing',
                )}
              >
                <div className="flex items-center gap-2">
                  <GripVertical size={12} className="text-(--color-text-subtle)" />
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
      </motion.div>
    </>
  )
}
