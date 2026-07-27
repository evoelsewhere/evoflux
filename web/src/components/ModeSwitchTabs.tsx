/**
 * ModeSwitchTabs — the Forge | Coding | AIM switcher shared by every
 * sidebar. One source of truth for the tab strip (plus an icon-rail
 * variant for the collapsed sidebar); previously each sidebar hand-rolled
 * its own copy and they drifted (missing active states, dead buttons).
 */

import { useNavigate } from '@tanstack/react-router'
import { motion } from 'framer-motion'
import { ArrowRightLeft, Code2, Gauge } from 'lucide-react'
import { useMotionPreset } from '@/lib/motion'
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
  const preset = useMotionPreset()
  const activeIndex = TABS.findIndex((tab) => tab.mode === active)
  return (
    // The strip is a size container: labels only render when there's room
    // for all three (below ~12.5rem the resizable sidebars would otherwise
    // clip the text), collapsing gracefully to icons + tooltips.
    <div className={cn('@container/modeswitch', className)}>
      <div className="relative grid h-9 grid-cols-3 items-center rounded-lg border border-(--color-border) bg-(--bg-page) p-0.5">
        <motion.div
          data-testid="mode-switch-indicator"
          data-active-mode={active}
          aria-hidden="true"
          className="pointer-events-none absolute bottom-0.5 left-0.5 top-0.5 w-[calc((100%-0.25rem)/3)] rounded-md bg-(--bg-key) shadow-sm"
          initial={false}
          animate={{ x: `${Math.max(0, activeIndex) * 100}%` }}
          transition={preset.spring}
        />
        {TABS.map(({ mode, label, Icon, to }) => (
          <button
            key={mode}
            type="button"
            onClick={() => {
              if (mode === active) return
              navigate({ to })
              onNavigate?.()
            }}
            title={label}
            aria-current={mode === active ? 'page' : undefined}
            className={cn(
              'relative z-10 flex h-8 min-w-0 items-center justify-center gap-1.5 rounded-md px-1 text-xs font-medium outline-none transition-[color,transform] duration-(--motion-fast) active:translate-y-px focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-(--color-accent)/35 @[12.5rem]/modeswitch:px-2',
              mode === active
                ? 'text-(--color-text)'
                : 'text-(--color-text-muted) hover:text-(--color-text)',
            )}
          >
            <Icon size={13} className="shrink-0" aria-hidden="true" />
            <span className="hidden whitespace-nowrap @[12.5rem]/modeswitch:inline">{label}</span>
          </button>
        ))}
      </div>
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
  const preset = useMotionPreset()
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
          aria-current={mode === active ? 'page' : undefined}
          className={cn(
            'relative flex h-8 w-8 items-center justify-center rounded-lg outline-none transition-[color,transform] duration-(--motion-fast) active:translate-y-px focus-visible:ring-2 focus-visible:ring-(--color-accent)/35',
            mode === active
              ? 'text-(--color-accent)'
              : 'text-(--color-text-subtle) hover:text-(--color-text-2)',
          )}
        >
          {mode === active && (
            <motion.span
              layoutId="mode-switch-rail-indicator"
              transition={preset.spring}
              className="absolute inset-0 rounded-lg bg-(--bg-key)"
              aria-hidden="true"
            />
          )}
          <Icon size={16} className="relative z-10" aria-hidden="true" />
        </button>
      ))}
    </div>
  )
}
