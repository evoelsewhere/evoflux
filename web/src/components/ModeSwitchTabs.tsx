/**
 * ModeSwitchTabs — the canonical Forge | Coding | AIM control. Desktop uses
 * one root-owned instance that survives route changes; transient mobile
 * drawers reuse the same control. ModeSwitchRail is its collapsed variant.
 */

import { useNavigate, useRouter } from '@tanstack/react-router'
import { motion } from 'framer-motion'
import { ArrowRightLeft, Code2, Gauge } from 'lucide-react'
import { useMotionPreset } from '@/lib/motion'
import { loadModeRoute } from '@/lib/mode-route'
import { cn } from '@/lib/utils'

export type AppMode = 'forge' | 'coding' | 'aim'

const TABS: Array<{ mode: AppMode; label: string; Icon: typeof Gauge; to: string }> = [
  { mode: 'forge', label: 'Forge', Icon: Gauge, to: '/' },
  { mode: 'coding', label: 'Coding', Icon: Code2, to: '/coding' },
  { mode: 'aim', label: 'AIM', Icon: ArrowRightLeft, to: '/aim' },
]

function useAnimatedModeNavigation(onNavigate?: () => void) {
  const navigate = useNavigate()
  const router = useRouter()
  const preset = useMotionPreset()

  const routeForMode = (mode: AppMode, fallback: string) =>
    loadModeRoute(mode) ?? fallback

  const preloadMode = (mode: AppMode, fallback: string) => {
    const to = routeForMode(mode, fallback)
    void router.preloadRoute({ to }).catch(() => {
      // Navigation itself remains available if an intent preload is cancelled
      // or a saved dynamic route no longer exists.
    })
  }

  const switchMode = (mode: AppMode, fallback: string) => {
    const to = routeForMode(mode, fallback)
    void navigate({ to }).then(
      () => onNavigate?.(),
      () => onNavigate?.(),
    )
  }

  return { preset, preloadMode, switchMode }
}

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
  const { preset, preloadMode, switchMode } = useAnimatedModeNavigation(onNavigate)
  const activeIndex = TABS.findIndex((tab) => tab.mode === active)
  return (
    // The strip is a size container: labels only render when there's room
    // for all three (below ~12.5rem the resizable sidebars would otherwise
    // clip the text), collapsing gracefully to icons + tooltips.
    <div className={cn('@container/modeswitch', className)}>
      <div
        className="relative grid h-10 grid-cols-3 items-center rounded-xl bg-(--bg-key)/55 p-1 shadow-[inset_0_0_0_1px_var(--color-border)]"
        role="tablist"
        aria-label="Application mode"
      >
        <motion.div
          data-testid="mode-switch-indicator"
          data-active-mode={active}
          aria-hidden="true"
          className="pointer-events-none absolute bottom-1 left-1 top-1 w-[calc((100%-0.5rem)/3)] rounded-lg bg-(--bg-card) shadow-[0_1px_4px_rgba(0,0,0,0.08),0_0_0_1px_var(--color-border)]"
          initial={false}
          animate={{ x: `${Math.max(0, activeIndex) * 100}%` }}
          transition={preset.spring}
        />
        {TABS.map(({ mode, label, Icon, to }) => (
          <button
            key={mode}
            type="button"
            onPointerEnter={() => {
              if (mode !== active) preloadMode(mode, to)
            }}
            onFocus={() => {
              if (mode !== active) preloadMode(mode, to)
            }}
            onClick={() => {
              if (mode !== active) switchMode(mode, to)
            }}
            title={label}
            aria-current={mode === active ? 'page' : undefined}
            aria-selected={mode === active}
            role="tab"
            className={cn(
              'relative z-10 flex h-8 min-w-0 items-center justify-center gap-1.5 rounded-lg px-1 text-xs font-medium outline-none transition-[color,transform] duration-(--motion-fast) active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-(--color-accent)/35 @[12.5rem]/modeswitch:px-2',
              mode === active
                ? 'text-(--color-text)'
                : 'text-(--color-text-subtle) hover:text-(--color-text)',
            )}
          >
            <Icon
              size={13}
              className={cn(
                'shrink-0 transition-colors duration-(--motion-fast)',
                mode === active && 'text-(--color-accent)',
              )}
              aria-hidden="true"
            />
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
  const { preset, preloadMode, switchMode } = useAnimatedModeNavigation()
  return (
    <div className={cn('flex flex-col items-center gap-0.5', className)}>
      {TABS.map(({ mode, label, Icon, to }) => (
        <button
          key={mode}
          type="button"
          onPointerEnter={() => {
            if (mode !== active) preloadMode(mode, to)
          }}
          onFocus={() => {
            if (mode !== active) preloadMode(mode, to)
          }}
          onClick={() => {
            if (mode !== active) switchMode(mode, to)
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
