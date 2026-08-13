/**
 * SidebarShell — the shared desktop chrome of the mode sidebars
 * (work / coding): a floating-card panel with resizable width,
 * collapse-to-zero animation, and the macOS traffic-light inset.
 *
 * Shared by Sidebar.tsx / CodingSidebar.tsx — both mode sidebars compose
 * this shell instead of duplicating the mechanics.
 * The shell owns:
 *   - one canonical width in `useUIStore` (persisted drag + dbl-click reset)
 *   - the resize-handle separator and direct, non-tweened pointer updates
 *   - the collapse/expand animation (follows the user's motion intensity)
 *   - a true zero-width collapsed state; AppShell keeps the restore control
 *     available outside the sidebar
 *
 * It deliberately does NOT own the mobile drawer (work/coding keep their
 * own overlay markup) or the `pt-10` traffic-light content inset — that
 * padding belongs to the first section inside a card, so callers keep
 * applying the `isMacOverlay ? 'pt-10' : 'pt-2'` ternary to their own
 * top section, as before.
 *
 * Two layout styles compose from the same pieces:
 *   (a) one floating card with internal dividers (work):
 *       `<SidebarCard className="h-full">…sections + <SidebarShellDivider/>…</SidebarCard>`
 *   (b) stacked separate cards per section (coding): several `<SidebarCard>`
 *       children — the shell's `gap-1 p-1` column spaces them.
 */

import {
  useCallback,
  useEffect,
  useRef,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react'
import { HelpCircle, Search, Settings } from 'lucide-react'
import { usePlatform } from '@/hooks/use-platform'
import { DURATIONS, useMotionPreset } from '@/lib/motion'
import { SIDEBAR_WIDTH, useUIStore } from '@/stores/useUIStore'
import { ThemeToggle } from '@/components/ThemeToggle'
import { HealthDot } from '@/components/HealthDot'
import { cn } from '@/lib/utils'
import { formatShortcutLabel } from '@/lib/keyboard-shortcuts'

interface SidebarShellProps {
  /** Fully hidden state — owned by the caller. */
  collapsed?: boolean
  /** aria-label of the resize handle (each sidebar names itself). */
  resizeLabel?: string
  children: ReactNode
}

export function SidebarShell({
  collapsed = false,
  resizeLabel = 'Resize sidebar',
  children,
}: SidebarShellProps) {
  const { isTauri, os } = usePlatform()
  const isDesktopShell = isTauri && os !== 'ios' && os !== 'android'
  const motionPreset = useMotionPreset()
  const sidebarWidth = useUIStore((state) => state.sidebarWidth)
  const setSidebarResizing = useUIStore((state) => state.setSidebarResizing)
  const setSidebarWidth = useUIStore((state) => state.setSidebarWidth)
  const resetSidebarWidth = useUIStore((state) => state.resetSidebarWidth)
  const resizeCleanupRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    return () => {
      resizeCleanupRef.current?.()
      resizeCleanupRef.current = null
    }
  }, [])

  const startResize = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (collapsed || event.pointerType === 'touch') return
    event.preventDefault()
    event.stopPropagation()

    const shell = event.currentTarget.closest<HTMLElement>('[data-sidebar-shell]')
    if (!shell) return

    // Drop any prior drag (rare) before attaching a new one.
    resizeCleanupRef.current?.()

    const navigation = document.querySelector<HTMLElement>(
      '[data-sidebar-width-follower]',
    )
    const shellTransition = shell.style.transition
    const navigationTransition = navigation?.style.transition ?? ''
    const startX = event.clientX
    // Read the rendered width so grabbing the handle also cancels an
    // in-flight expand animation at its current position.
    const startWidth = Math.min(
      SIDEBAR_WIDTH.max,
      Math.max(SIDEBAR_WIDTH.min, shell.getBoundingClientRect().width),
    )
    let liveWidth = startWidth
    let finished = false

    const applyLiveWidth = (width: number) => {
      shell.style.width = `${width}px`
      shell.style.minWidth = `${width}px`
      if (navigation) navigation.style.width = `${Math.max(0, width - 8)}px`
    }

    // CSS owns the collapse/expand transition, but pointer movement must be
    // direct. Pin the currently rendered size before disabling transitions
    // so an unfinished expand cannot keep tweening underneath the drag.
    shell.style.transition = 'none'
    if (navigation) navigation.style.transition = 'none'
    applyLiveWidth(startWidth)
    setSidebarResizing(true)

    const handleMove = (moveEvent: PointerEvent) => {
      liveWidth = Math.min(
        SIDEBAR_WIDTH.max,
        Math.max(
          SIDEBAR_WIDTH.min,
          startWidth + moveEvent.clientX - startX,
        ),
      )
      // Do not route pointer-rate updates through React/Zustand/localStorage.
      // Direct writes keep both pieces of sidebar chrome under the cursor.
      applyLiveWidth(liveWidth)
    }
    const finish = (commit: boolean) => {
      if (finished) return
      finished = true
      window.removeEventListener('pointermove', handleMove)
      window.removeEventListener('pointerup', handleUp)
      window.removeEventListener('pointercancel', handleUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      resizeCleanupRef.current = null
      if (commit) {
        // Commit once while transitions are still disabled. The DOM is already
        // at this exact width, so restoring transitions on the next frame does
        // not create a second "catch-up" animation after pointerup.
        setSidebarWidth(liveWidth)
      }
      setSidebarResizing(false)
      if (useUIStore.getState().sidebarCollapsed) {
        applyLiveWidth(0)
      }
      window.requestAnimationFrame(() => {
        shell.style.transition = shellTransition
        if (navigation) navigation.style.transition = navigationTransition
      })
    }
    const handleUp = () => finish(true)

    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', handleMove)
    window.addEventListener('pointerup', handleUp, { once: true })
    window.addEventListener('pointercancel', handleUp, { once: true })
    resizeCleanupRef.current = () => finish(false)
  }, [collapsed, setSidebarResizing, setSidebarWidth])

  const width = collapsed ? 0 : sidebarWidth
  const transitionDuration = DURATIONS.base * motionPreset.scale

  return (
    <aside
      data-sidebar-shell
      aria-hidden={collapsed || undefined}
      data-desktop-sidebar-glass={isDesktopShell ? 'true' : undefined}
      className="relative flex h-full shrink-0 flex-col overflow-hidden"
      style={{
        width,
        minWidth: width,
        transition: [
          `width ${transitionDuration}ms var(--ease-out)`,
          `min-width ${transitionDuration}ms var(--ease-out)`,
        ].join(', '),
      }}
    >
      {!collapsed && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label={resizeLabel}
          title="Drag to resize · double-click to reset"
          className="absolute right-0 top-0 z-(--z-header) h-full w-1 cursor-col-resize transition-colors hover:bg-(--color-accent)/40"
          onPointerDown={startResize}
          onDoubleClick={resetSidebarWidth}
        />
      )}
      <div className="flex h-full flex-col gap-0.5 overflow-hidden p-0.5">
        {!collapsed && children}
      </div>
    </aside>
  )
}

/**
 * The floating region card every sidebar section lives in. Height/flex
 * behaviour comes from the caller: `className="h-full"` for the single-card
 * layout, `w-full shrink-0 …` for rail/stack cards.
 */
export function SidebarCard({
  className,
  children,
}: {
  className?: string
  children: ReactNode
}) {
  return (
    <div
      data-sidebar-card
      className={cn(
        'flex min-h-0 flex-col overflow-hidden rounded-md bg-(--bg-sidebar)/80 backdrop-blur-xl',
        className,
      )}
    >
      {children}
    </div>
  )
}

/** In-card section separator (the work pattern: a hairline inset by mx-3). */
export function SidebarShellDivider({ className }: { className?: string }) {
  return (
    <div className={cn('shrink-0 h-px bg-(--color-border)', className ?? 'mx-3')} />
  )
}

/**
 * Space occupied by the root-owned desktop mode navigation. Route sidebars
 * render this inert slot instead of mounting their own copy of the switcher.
 */
export function SidebarModeSlot({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn('h-10 shrink-0', className)} />
}

/**
 * Fake search input that opens the command palette (Ctrl+P). Canonical
 * background is `bg-(--bg-page)` (the work variant).
 */
export function SidebarSearchTrigger({
  onClick,
}: {
  onClick?: () => void
}) {
  const shortcut = formatShortcutLabel('^P')
  return (
    <button
      type="button"
      onClick={onClick}
      className="focus-ring-control group flex h-9 w-full items-center gap-2 rounded-xl border border-transparent bg-(--bg-key)/40 px-2.5 text-left text-xs text-(--color-text-muted) shadow-[inset_0_0_0_1px_var(--color-border)] transition-[background-color,color,box-shadow] duration-(--motion-fast) hover:bg-(--bg-key)/70 hover:text-(--color-text-2) hover:shadow-[inset_0_0_0_1px_var(--color-border-strong)]"
      aria-label="Open command palette"
      title={`Open command palette (${shortcut})`}
    >
      <Search size={13} className="text-(--color-text-subtle) transition-colors group-hover:text-(--color-text-muted)" aria-hidden="true" />
      <span className="flex-1">Search…</span>
      <kbd className="rounded-md bg-(--bg-card)/75 px-1.5 py-1 font-sans text-[11px] font-medium leading-none tracking-normal text-(--color-text-muted) shadow-[inset_0_0_0_1px_var(--color-border)]">{shortcut}</kbd>
    </button>
  )
}

interface SidebarFooterProps {
  /** Opens the command palette (Search). Help always opens Guidelines. */
  onCommandPalette?: () => void
  /** Icon-rail variant: vertical stack (Settings · Help · theme · health). */
  collapsed?: boolean
  /** Runs after the Settings / Help action (e.g. close the mobile drawer). */
  onAction?: () => void
}

/** Footer trio — Settings + Help | HealthDot + ThemeToggle. */
export function SidebarFooter({
  collapsed = false,
  onAction,
}: SidebarFooterProps) {
  const openSettings = () => {
    useUIStore.getState().openSettings()
    onAction?.()
  }
  const openHelp = () => {
    useUIStore.getState().openGuidelines()
    onAction?.()
  }

  if (collapsed) {
    return (
      <div className="flex w-full shrink-0 flex-col items-center gap-1 px-1 py-2">
        <button
          type="button"
          onClick={openSettings}
          className="focus-ring-control press-control flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
          aria-label="Settings"
          title="Settings"
        >
          <Settings size={14} aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={openHelp}
          className="focus-ring-control press-control flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
          aria-label="Guidelines"
          title="Guidelines"
          data-testid="sidebar-guidelines-button"
        >
          <HelpCircle size={14} aria-hidden="true" />
        </button>
        <ThemeToggle collapsed />
        <HealthDot />
      </div>
    )
  }

  return (
    <div className="flex shrink-0 items-center justify-between gap-2 px-2 py-1.5 pb-safe">
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={openSettings}
          className="focus-ring-control press-control flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
          aria-label="Settings"
          title="Settings"
        >
          <Settings size={14} aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={openHelp}
          className="focus-ring-control press-control flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
          aria-label="Guidelines"
          title="Guidelines"
          data-testid="sidebar-guidelines-button"
        >
          <HelpCircle size={14} aria-hidden="true" />
        </button>
      </div>
      <div className="flex items-center gap-2">
        <HealthDot />
        <ThemeToggle collapsed />
      </div>
    </div>
  )
}
