/**
 * CollapsibleSection — the canonical sidebar section header: uppercase
 * label with an optional collapse chevron, an optional count pill, and an
 * optional "+" action button on the right.
 *
 * Canonical label style (one source of truth; the three sidebars had
 * drifted): `text-[10px] font-semibold uppercase tracking-wider`.
 *
 * Pass `onToggle` to make the label an expand/collapse button with a
 * chevron (coding's Projects/Workspaces headers); omit it for a static
 * label (aim's Projects header).
 */

import { ChevronDown, ChevronRight, Plus } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { LucideIcon } from 'lucide-react'

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
  className,
}: CollapsibleSectionProps) {
  const pill = count !== undefined && (
    <span className="rounded-full bg-(--bg-key) px-1.5 py-px text-[9px] font-semibold normal-case tracking-normal text-(--color-text-subtle)">
      {count}
    </span>
  )

  return (
    <div className={cn('flex items-center justify-between px-1 pb-1', className)}>
      {onToggle ? (
        <button
          type="button"
          onClick={onToggle}
          className="flex min-w-0 flex-1 items-center gap-1 rounded-xs py-0.5 text-left hover:bg-(--bg-key)"
          aria-expanded={!collapsed}
          // Keep the verb outside the placeholder: a whole-sentence frame lets the
          // catalog carry a specific "Collapse {0} section" entry instead of
          // falling back to the generic "{0} {1} section" wildcard.
          aria-label={collapsed ? `Expand ${label} section` : `Collapse ${label} section`}
        >
          {collapsed ? (
            <ChevronRight
              size={10}
              className="shrink-0 text-(--color-text-muted)"
              aria-hidden="true"
            />
          ) : (
            <ChevronDown
              size={10}
              className="shrink-0 text-(--color-text-muted)"
              aria-hidden="true"
            />
          )}
          <span className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-muted)">
            {label}
          </span>
          {pill}
        </button>
      ) : (
        <span className="flex min-w-0 flex-1 items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-(--color-text-muted)">
          {label}
          {pill}
        </span>
      )}
      {onAdd && (
        <button
          type="button"
          onClick={onAdd}
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text)"
          title={addLabel}
          aria-label={addLabel}
        >
          <AddIcon size={12} aria-hidden="true" />
        </button>
      )}
    </div>
  )
}
