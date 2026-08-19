/**
 * SidebarItem — sidebar nav row with icon, label, and optional keyboard hint.
 *
 * Pencil component `F3DZn` (SidebarItem) covers the nav rows in
 * `Urcca` (Sidebar/Expanded). 40h, padding [10,12], gap 10, radius-md.
 *
 * Two render modes:
 *   - expanded: [icon] [label .....] [kbd?]
 *   - collapsed: [icon] (centered, 40×40 square, no label, no kbd)
 *
 * Active / hover styling matches paper-token nav: hover bumps weight from
 * 500→600 via `interactive-weight`, active uses `--bg-key` fill.
 */
import { motion, AnimatePresence } from 'framer-motion'
import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'
import type { ComponentType, MouseEventHandler, ReactNode } from 'react'
import { formatShortcutLabel } from '@/lib/keyboard-shortcuts'

/**
 * Convert the shorthand ``"^N"`` (caret = primary modifier) into a
 * ``"Ctrl+N"`` label. Anything else is rendered as-is.
 */
export interface SidebarItemProps {
  /** Lucide icon component (or any component accepting `size` prop). */
  Icon: ComponentType<{ size?: number; className?: string }>
  label: string
  /** Keyboard hint text shown on the right of the row when expanded. */
  kbd?: string
  active?: boolean
  collapsed?: boolean
  /** Denser desktop row; touch drawers keep the default target size. */
  compact?: boolean
  onClick?: MouseEventHandler<HTMLButtonElement>
  title?: string
  /** Optional override for the right-side slot when expanded. */
  rightSlot?: ReactNode
  className?: string
}

export function SidebarItem({
  Icon,
  label,
  kbd,
  active = false,
  collapsed = false,
  compact = false,
  onClick,
  title,
  rightSlot,
  className,
}: SidebarItemProps) {
  const preset = useMotionPreset()

  return (
    <button
      type="button"
      onClick={onClick}
      title={title ?? (kbd ? `${label} (${formatShortcutLabel(kbd)})` : label)}
      aria-label={collapsed ? label : undefined}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'interactive-weight relative flex w-full items-center transition-colors',
        compact ? 'gap-2 rounded-md text-xs' : 'gap-2.5 rounded-lg text-sm',
        collapsed
          ? 'h-10 w-10 justify-center px-0 py-0'
          : compact
            ? 'h-8 px-2.5 py-0'
            : 'h-10 px-3 py-0',
        active
          ? 'arc-active-indicator bg-(--bg-key) text-(--color-accent) font-semibold'
          : 'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)',
        className,
      )}
    >
      <Icon size={compact ? 14 : 16} className="shrink-0" />
      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.span
            key="label"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={preset.transition}
            className="flex-1 truncate text-left whitespace-nowrap"
          >
            {label}
          </motion.span>
        )}
      </AnimatePresence>
      {!collapsed &&
        (rightSlot !== undefined ? (
          rightSlot
        ) : kbd ? (
          <kbd
            className={cn(
              'shrink-0 rounded border border-(--color-border) bg-(--bg-page) px-1.5 font-sans font-medium leading-none tracking-normal text-(--color-text-muted)',
              compact ? 'py-0.5 text-[10px]' : 'py-1 text-[11px]',
            )}
          >
            {formatShortcutLabel(kbd)}
          </kbd>
        ) : null)}
    </button>
  )
}
