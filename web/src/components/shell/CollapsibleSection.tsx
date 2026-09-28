/**
 * CollapsibleSection — the canonical sidebar section header: uppercase
 * label with an optional collapse chevron, an optional plain count, and an
 * optional "+" action button on the right.
 *
 * Canonical label style (one source of truth; the three sidebars had
 * drifted): `text-[10px] font-medium uppercase tracking-wide`, subtle.
 *
 * Pass `onToggle` to make the label an expand/collapse button with a
 * chevron (coding's Projects/Workspaces headers); omit it for a static
 * label (static section headers).
 */

import { ChevronDown, ChevronRight, Plus } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

interface CollapsibleSectionProps {
  label: string
  /** Collapsed state — only meaningful together with `onToggle`. */
  collapsed?: boolean
  /** When provided, the label becomes a chevron toggle button. */
  onToggle?: () => void
  /** Optional count pill rendered next to the label. */
  count?: number
  /** Optional "+" action button on the right. */
  onAdd?: () => void
  /** aria-label/title of the "+" action. */
  addLabel?: string
  /** Icon of the "+" action (e.g. FolderPlus for workspaces). */
  AddIcon?: LucideIcon
  /** Optional custom action rendered at the right edge of the header. */
  rightSlot?: ReactNode
  /** Larger label and controls for top-level navigation groups. */
  size?: 'default' | 'large'
  className?: string
}

export function CollapsibleSection({
  label,
  collapsed = false,
  onToggle,
  count,
  onAdd,
  addLabel,
  AddIcon = Plus,
  rightSlot,
  size = 'default',
  className,
}: CollapsibleSectionProps) {
  const large = size === 'large'
  const countLabel = count !== undefined && (
    <span
      className={cn(
        'font-normal normal-case tracking-normal tabular-nums text-(--color-text-subtle)',
        large ? 'text-xs' : 'text-[10px]',
      )}
    >
      {count}
    </span>
  )
  const labelClass = cn(
    'font-medium uppercase tracking-wide text-(--color-text-subtle)',
    large ? 'text-xs' : 'text-[10px]',
  )

  return (
    <div
      className={cn(
        'flex items-center justify-between px-1',
        large ? 'pb-2 pt-1' : 'pb-1',
        className,
      )}
    >
      {onToggle ? (
        <button
          type="button"
          onClick={onToggle}
          className={cn(
            'flex min-w-0 flex-1 items-center rounded-xs text-left',
            large ? 'gap-1.5 py-1' : 'gap-1 py-0.5',
          )}
          aria-expanded={!collapsed}
          aria-label={`${collapsed ? 'Expand' : 'Collapse'} ${label} section`}
        >
          {collapsed ? (
            <ChevronRight
              size={large ? 12 : 10}
              className="shrink-0 text-(--color-text-subtle)"
              aria-hidden="true"
            />
          ) : (
            <ChevronDown
              size={large ? 12 : 10}
              className="shrink-0 text-(--color-text-subtle)"
              aria-hidden="true"
            />
          )}
          <span className={labelClass}>{label}</span>
          {countLabel}
        </button>
      ) : (
        <span className={cn('flex min-w-0 flex-1 items-center gap-1', labelClass)}>
          {label}
          {countLabel}
        </span>
      )}
      {(rightSlot || onAdd) && (
        <div className="flex shrink-0 items-center">
          {rightSlot ?? (
            <button
              type="button"
              onClick={onAdd}
              className={cn(
                'flex shrink-0 items-center justify-center rounded text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text)',
                large ? 'h-7 w-7' : 'h-5 w-5',
              )}
              title={addLabel}
              aria-label={addLabel}
            >
              <AddIcon size={large ? 15 : 12} aria-hidden="true" />
            </button>
          )}
        </div>
      )}
    </div>
  )
}
