/**
 * SidebarItem — sidebar nav row with icon, label, and optional keyboard hint.
 *
 * Pencil component `F3DZn` (SidebarItem) covers the nav rows in
 * `Urcca` (Sidebar/Expanded). 40h, padding [10,12], gap 10, radius-md.
 *
 * Three render modes:
 *   - expanded: [icon] [label .....] [kbd?]
 *   - tile: icon over label in a 56px grid cell (kbd in the tooltip)
 *   - collapsed: [icon] (centered, 40×40 square, no label, no kbd)
 *
 * Labels sit at a steady 500 (a hover weight bump reflowed the row); hover
 * fills `--bg-key`, active adds the accent and 600. The kbd hint appears on
 * hover/focus only.
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
  /**
   * Grid tile (icon over label) for `<SidebarNavGroup grid>`. The kbd hint
   * is left to the tooltip — a tile has no room for it.
   */
  tile?: boolean
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
  tile = false,
  onClick,
  title,
  rightSlot,
  className,
}: SidebarItemProps) {
  const preset = useMotionPreset()
  const tooltip = title ?? (kbd ? `${label} (${formatShortcutLabel(kbd)})` : label)

  if (tile && !collapsed) {
    return (
      <button
        type="button"
        onClick={onClick}
        title={tooltip}
        aria-current={active ? 'page' : undefined}
        data-sidebar-item
        className={cn(
          'flex h-14 min-w-0 flex-col items-center justify-center gap-1 rounded-lg px-1 text-[11px] font-medium transition-colors',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)',
          active
            ? 'bg-(--color-text)/8 text-(--color-accent)'
            : 'bg-(--color-text)/4 text-(--color-text-2) hover:bg-(--color-text)/8 hover:text-(--color-text)',
          className,
        )}
      >
        <Icon size={16} className="shrink-0" />
        {/* Two lines before clipping: a long label ("Source Control")
            wraps instead of losing its second word. */}
        <span className="line-clamp-2 w-full text-center leading-tight break-words">{label}</span>
      </button>
    )
  }

  return (
    <button
      type="button"
      onClick={onClick}
      title={tooltip}
      aria-label={collapsed ? label : undefined}
      aria-current={active ? 'page' : undefined}
      data-sidebar-item
      className={cn(
        'group/sidebar-item relative flex w-full items-center font-medium transition-colors',
        compact ? 'gap-2 rounded-md text-xs' : 'gap-2.5 rounded-lg text-sm',
        collapsed
          ? 'h-10 w-10 justify-center px-0 py-0'
          : compact
            ? 'h-8 px-2.5 py-0'
            : 'h-10 px-3 py-0',
        active
          ? 'arc-active-indicator bg-(--color-text)/7 text-(--color-accent) font-semibold'
          : 'text-(--color-text-2) hover:bg-(--color-text)/4 hover:text-(--color-text)',
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
          // Revealed on hover/focus only: a boxed hint on every row outweighed
          // the labels, and the row's title carries the shortcut for everyone.
          <kbd
            className={cn(
              'shrink-0 rounded border border-(--color-border) bg-(--bg-page) px-1.5 font-sans font-medium leading-none tracking-normal text-(--color-text-muted)',
              'opacity-0 transition-opacity duration-(--motion-fast) group-hover/sidebar-item:opacity-100 group-focus-visible/sidebar-item:opacity-100 pointer-coarse:hidden',
              compact ? 'py-0.5 text-[10px]' : 'py-1 text-[11px]',
            )}
          >
            {formatShortcutLabel(kbd)}
          </kbd>
        ) : null)}
    </button>
  )
}
