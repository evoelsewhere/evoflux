/**
 * FloatingTodosPanel — floating task list that can be dragged anywhere.
 *
 * A draggable, toggleable panel that shows the task list. Can be minimized
 * to just a floating button with task count badge.
 *
 * Uses manual pointer-based drag (no framer-motion drag) to avoid
 * AnimatePresence conflicts that cause disappearing on drag.
 */

import { useState, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { CheckSquare, X, Minimize2, GripVertical } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useMotionPreset } from '@/lib/motion'
import { TodosList } from './TodosList'
import type { TodoItem } from '@/api/types'

export interface FloatingTodosPanelProps {
  todos?: TodoItem[]
  className?: string
}

const PANEL_WIDTH = 320 // w-80 = 20rem = 320px
const MARGIN = 16
const DEFAULT_TOP = 48

export function FloatingTodosPanel({ todos, className }: FloatingTodosPanelProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [isMinimized, setIsMinimized] = useState(false)
  const preset = useMotionPreset()

  /* Absolute pixel position (top-right anchor by default) */
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const [isDragging, setIsDragging] = useState(false)

  const dragState = useRef({
    startX: 0,
    startY: 0,
    startPosX: 0,
    startPosY: 0,
    didDrag: false,   // whether any actual movement happened
  })

  const todoCount = todos?.length ?? 0
  const finishedCount = todos?.filter(
    (t) => t.status === 'completed' || t.status === 'cancelled',
  ).length ?? 0
  const pendingCount = todoCount - finishedCount

  // Default position: top-right corner
  const defaultX =
    typeof window !== 'undefined'
      ? window.innerWidth - PANEL_WIDTH - MARGIN
      : 200
  const x = pos?.x ?? defaultX
  const y = pos?.y ?? DEFAULT_TOP

  /* ── pointer-based drag ────────────────────────────────────── */

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      // Only drag from the grip handle or header area
      const target = e.target as HTMLElement
      if (target.closest('[data-drag-handle]') === null) return

      e.preventDefault()
      e.stopPropagation()

      setIsDragging(true)
      dragState.current = {
        startX: e.clientX,
        startY: e.clientY,
        startPosX: x,
        startPosY: y,
        didDrag: false,
      }

      const onPointerMove = (ev: PointerEvent) => {
        const dx = ev.clientX - dragState.current.startX
        const dy = ev.clientY - dragState.current.startY
        // Mark as dragged only if moved more than 3px (avoid accidental clicks)
        if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
          dragState.current.didDrag = true
        }
        setPos({
          x: dragState.current.startPosX + dx,
          y: dragState.current.startPosY + dy,
        })
      }

      const onPointerUp = () => {
        setIsDragging(false)
        window.removeEventListener('pointermove', onPointerMove)
        window.removeEventListener('pointerup', onPointerUp)
        // If we didn't actually drag, treat it as a click
        if (!dragState.current.didDrag) {
          // Let the original click handler proceed
          return
        }
        // If we did drag, suppress the click event
        // Prevent click from firing by capturing the next click
        const suppressClick = (ev: MouseEvent) => {
          ev.stopPropagation()
          ev.preventDefault()
          window.removeEventListener('click', suppressClick, true)
        }
        window.addEventListener('click', suppressClick, true)
      }

      window.addEventListener('pointermove', onPointerMove)
      window.addEventListener('pointerup', onPointerUp)
    },
    [x, y],
  )

  /* ── safe click handlers (ignore if just dragged) ─────────── */

  const handleToggleClick = useCallback(() => {
    if (!dragState.current.didDrag) {
      setIsOpen(true)
    }
  }, [])

  const handleMinimizedClick = useCallback(() => {
    if (!dragState.current.didDrag) {
      setIsMinimized(false)
    }
  }, [])

  // Don't render if no todos
  if (todoCount === 0) return null

  /* ── render ────────────────────────────────────────────────── */

  return (
    <div
      className={cn('fixed z-(--z-modal) select-none', className)}
      style={{ left: x, top: y, width: PANEL_WIDTH }}
    >
      <AnimatePresence initial={false}>
        {!isOpen ? (
          /* ── Floating toggle button ── */
          <motion.button
            key="toggle"
            data-drag-handle
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.8, opacity: 0 }}
            transition={preset.spring}
            type="button"
            onPointerDown={onPointerDown}
            onClick={handleToggleClick}
            className={cn(
              'flex h-10 items-center gap-2 rounded-lg border border-(--color-border)',
              'bg-(--bg-card) px-3 shadow-lg transition-colors',
              isDragging ? 'cursor-grabbing' : 'cursor-grab',
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
          /* ── Minimized: button with count ── */
          <motion.button
            key="minimized"
            data-drag-handle
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.8, opacity: 0 }}
            transition={preset.spring}
            type="button"
            onPointerDown={onPointerDown}
            onClick={handleMinimizedClick}
            className={cn(
              'flex h-10 items-center gap-2 rounded-lg border border-(--color-border)',
              'bg-(--bg-card) px-3 shadow-lg transition-colors',
              isDragging ? 'cursor-grabbing' : 'cursor-grab',
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
          /* ── Full panel ── */
          <motion.div
            key="panel"
            initial={{ scale: 0.95, opacity: 0, y: -10 * preset.distance }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.95, opacity: 0, y: -10 * preset.distance }}
            transition={preset.spring}
            className={cn(
              'rounded-lg border border-(--color-border)',
              'bg-(--bg-card) shadow-xl',
            )}
          >
            {/* Header — drag handle */}
            <div
              data-drag-handle
              onPointerDown={onPointerDown}
              className={cn(
                'flex items-center justify-between border-b border-(--color-border) px-3 py-2',
                isDragging ? 'cursor-grabbing' : 'cursor-grab',
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
                  className="flex h-6 w-6 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                  title="Minimize"
                >
                  <Minimize2 size={12} />
                </button>
                <button
                  type="button"
                  onClick={() => setIsOpen(false)}
                  className="flex h-6 w-6 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
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