/**
 * ModeSwitchTabs — the Forge | Coding | AIM switcher shared by every
 * sidebar. One source of truth for the tab strip (plus an icon-rail
 * variant for the collapsed sidebar); previously each sidebar hand-rolled
 * its own copy and they drifted (missing active states, dead buttons).
 */

import { useNavigate } from '@tanstack/react-router'
import { ArrowRightLeft, Code2, Gauge } from 'lucide-react'
import { cn } from '@/lib/utils'

export type AppMode = 'forge' | 'coding' | 'aim'

const TABS: Array<{ mode: AppMode; label: string; Icon: typeof Gauge; to: string }> = [
  { mode: 'forge', label: 'Forge', Icon: Gauge, to: '/' },
  { mode: 'coding', label: 'Coding', Icon: Code2, to: '/coding' },
  { mode: 'aim', label: 'AIM', Icon: ArrowRightLeft, to: '/aim' },
]

export function ModeSwitchTabs({
  active,
  onNavigate,
  className,
}: {
  active: AppMode
  /** Runs after switching modes (e.g. close the mobile drawer). */
  onNavigate?: () => void
  className?: string
}) {
  const navigate = useNavigate()
  return (
    <div
      className={cn(
        'flex h-8 items-center rounded-md border border-(--color-border) bg-(--bg-page) p-0.5',
        className,
      )}
    >
      {TABS.map(({ mode, label, Icon, to }) => (
        <button
          key={mode}
          type="button"
          onClick={() => {
            if (mode === active) return
            navigate({ to })
            onNavigate?.()
          }}
          className={cn(
            'flex h-full flex-1 items-center justify-center gap-1.5 rounded-[5px] px-2 text-xs font-medium transition-colors',
            mode === active
              ? 'bg-(--bg-key) text-(--color-text) shadow-sm'
              : 'text-(--color-text-muted) hover:text-(--color-text)',
          )}
        >
          <Icon size={12} aria-hidden="true" />
          {label}
        </button>
      ))}
    </div>
  )
}

/** Icon-only variant for the collapsed (icon rail) sidebar. */
export function ModeSwitchRail({
  active,
  className,
}: {
  active: AppMode
  className?: string
}) {
  const navigate = useNavigate()
  return (
    <div className={cn('flex flex-col items-center gap-0.5', className)}>
      {TABS.map(({ mode, label, Icon, to }) => (
        <button
          key={mode}
          type="button"
          onClick={() => {
            if (mode !== active) navigate({ to })
          }}
          title={label}
          className={cn(
            'flex h-8 w-8 items-center justify-center rounded-md transition-colors',
            mode === active
              ? 'bg-(--bg-key) text-(--color-accent)'
              : 'text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text-2)',
          )}
        >
          <Icon size={16} aria-hidden="true" />
        </button>
      ))}
    </div>
  )
}
