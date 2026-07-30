/**
 * ViewToggle — icon-only segmented control: Agent (focused) vs Split
 * (side-by-side panes). Labels live on `aria-label` / `title` because
 * the topbar is too dense for inline text. The pencil mock draws an
 * outer border; we drop it so the toggle reads as part of the same
 * cluster as the bordered status pill and chip dropdown next to it.
 */

import type { LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  FocusViewIcon,
  MonitorViewIcon,
  SplitViewIcon,
} from '@/components/ui/layout-icons'

export type ViewMode = 'agent' | 'split' | 'monitor'

interface ModeDef {
  mode: ViewMode
  label: string
  Icon: LucideIcon
}

const MODES: readonly ModeDef[] = [
  { mode: 'agent', label: 'Agent view', Icon: FocusViewIcon },
  { mode: 'split', label: 'Split view', Icon: SplitViewIcon },
  { mode: 'monitor', label: 'Monitor view', Icon: MonitorViewIcon },
] as const

export interface ViewToggleProps {
  value: ViewMode
  onValueChange: (mode: ViewMode) => void
  className?: string
}

export function ViewToggle({
  value,
  onValueChange,
  className,
}: ViewToggleProps) {
  return (
    <div
      role="radiogroup"
      aria-label="View mode"
      className={cn(
        'inline-flex items-center overflow-hidden rounded-md p-0.5',
        className,
      )}
    >
      {MODES.map(({ mode, label, Icon }) => {
        const selected = value === mode
        return (
          <button
            key={mode}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={label}
            title={label}
            onClick={() => onValueChange(mode)}
            className={cn(
              'inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors',
              selected
                ? 'bg-(--color-surface-2) text-(--color-text)'
                : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text-2)',
            )}
          >
            <Icon size={15} aria-hidden="true" />
          </button>
        )
      })}
    </div>
  )
}
