/**
 * ModeSwitchTabs — the canonical Work | Coding control. Desktop uses
 * one root-owned instance that survives route changes; transient mobile
 * drawers reuse the same control.
 */

import { useNavigate, useRouter } from '@tanstack/react-router'
import { motion } from 'framer-motion'
import { CodeXml, Monitor, type LucideIcon } from 'lucide-react'
import type { KeyboardEvent } from 'react'
import { useMotionPreset } from '@/lib/motion'
import { loadModeRoute } from '@/lib/mode-route'
import { cn } from '@/lib/utils'

export type AppMode = 'work' | 'coding'

const TABS: Array<{ mode: AppMode; label: string; Icon: LucideIcon; to: string }> = [
  { mode: 'work', label: 'Work', Icon: Monitor, to: '/' },
  { mode: 'coding', label: 'Coding', Icon: CodeXml, to: '/coding' },
]

function ModeIcon({
  Icon,
  active,
}: {
  Icon: LucideIcon
  active: boolean
}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'grid shrink-0 place-items-center transition-[color,filter] duration-(--motion-fast)',
        'size-5',
        active
          ? 'text-(--color-accent) [filter:drop-shadow(0_0_3px_color-mix(in_srgb,var(--color-accent)_58%,transparent))]'
          : 'text-(--color-text-subtle) group-hover:text-(--color-text)',
      )}
    >
      <Icon
        size={15}
        strokeWidth={1.75}
        absoluteStrokeWidth
      />
    </span>
  )
}

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

  const onTabListKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const current = Math.max(0, activeIndex)
    let next = current
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      next = (current + 1) % TABS.length
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      next = (current - 1 + TABS.length) % TABS.length
    } else if (event.key === 'Home') {
      next = 0
    } else if (event.key === 'End') {
      next = TABS.length - 1
    } else {
      return
    }
    event.preventDefault()
    const tab = TABS[next]
    if (!tab) return
    if (tab.mode !== active) switchMode(tab.mode, tab.to)
    // Move focus to the newly selected tab after navigation kicks off.
    const buttons = event.currentTarget.querySelectorAll<HTMLElement>('[role="tab"]')
    buttons[next]?.focus()
  }

  return (
    // The strip is a size container: labels only render when there's room
    // for both modes (below ~12.5rem the resizable sidebars would otherwise
    // clip the text), collapsing gracefully to icons + tooltips.
    <div className={cn('@container/modeswitch', className)}>
      <div
        className="relative grid h-10 grid-cols-2 items-center rounded-xl bg-(--bg-key)/55 p-1 shadow-[inset_0_0_0_1px_var(--color-border)]"
        role="tablist"
        aria-label="Application mode"
        onKeyDown={onTabListKeyDown}
      >
        <motion.div
          data-testid="mode-switch-indicator"
          data-active-mode={active}
          aria-hidden="true"
          className="pointer-events-none absolute bottom-1 left-1 top-1 w-[calc((100%-0.5rem)/2)] rounded-lg bg-(--bg-card) shadow-[0_1px_4px_rgba(0,0,0,0.08),0_0_0_1px_var(--color-border)]"
          initial={false}
          animate={{ x: `${Math.max(0, activeIndex) * 100}%` }}
          transition={preset.spring}
        />
        {TABS.map(({ mode, label, Icon, to }) => (
          <button
            key={mode}
            type="button"
            tabIndex={mode === active ? 0 : -1}
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
              'group relative z-(--z-panel) flex h-8 min-w-0 items-center justify-center gap-1 rounded-lg px-1 text-xs font-medium outline-none transition-[color,transform] duration-(--motion-fast) active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-(--color-accent)/35 @[12.5rem]/modeswitch:gap-1.5 @[12.5rem]/modeswitch:px-2',
              mode === active
                ? 'text-(--color-accent)'
                : 'text-(--color-text-subtle) hover:text-(--color-text)',
            )}
          >
            <ModeIcon Icon={Icon} active={mode === active} />
            <span className="hidden whitespace-nowrap @[12.5rem]/modeswitch:inline">{label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
