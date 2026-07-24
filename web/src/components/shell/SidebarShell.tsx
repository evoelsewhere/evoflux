/**
 * SidebarShell — the shared desktop chrome of the three mode sidebars
 * (forge / coding / aim): a floating-card panel with resizable width,
 * collapse-to-icon-rail animation, and the macOS traffic-light inset.
 *
 * Shared by Sidebar.tsx / AimSidebar.tsx / CodingSidebar.tsx — all three
 * mode sidebars compose this shell instead of duplicating the mechanics.
 * The shell owns:
 *   - one canonical width in `useUIStore` (persisted drag + dbl-click reset)
 *   - the resize-handle separator and direct, non-tweened pointer updates
 *   - the collapse/expand animation (follows the user's motion intensity)
 *   - the collapsed rail width: 56px, or 70px on macOS overlay so the
 *     traffic lights land inside the rail
 *
 * It deliberately does NOT own the mobile drawer (forge/coding keep their
 * own overlay markup) or the `pt-10` traffic-light content inset — that
 * padding belongs to the first section inside a card, so callers keep
 * applying the `isMacOverlay ? 'pt-10' : 'pt-2'` ternary to their own
 * top section, as before.
 *
 * Two layout styles compose from the same pieces:
 *   (a) one floating card with internal dividers (forge/aim):
 *       `<SidebarCard className="h-full">…sections + <SidebarShellDivider/>…</SidebarCard>`
 *   (b) stacked separate cards per section (coding): several `<SidebarCard>`
 *       children — the shell's `gap-1 p-1` column spaces them.
 */

import {
  useCallback,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react'
import { motion } from 'framer-motion'
import { HelpCircle, Search, Settings } from 'lucide-react'
import { usePlatform } from '@/hooks/use-platform'
import { useMotionPreset } from '@/lib/motion'
import { useUIStore } from '@/stores/useUIStore'
import { ThemeToggle } from '@/components/ThemeToggle'
import { HealthDot } from '@/components/HealthDot'
import { cn } from '@/lib/utils'

interface SidebarShellProps {
  /** Collapsed icon-rail state — owned by the caller. */
  collapsed?: boolean
  /** Content rendered in place of `children` while collapsed. */
  rail?: ReactNode
  /** aria-label of the resize handle (each sidebar names itself). */
  resizeLabel?: string
  children: ReactNode
}

export function SidebarShell({
  collapsed = false,
  rail,
  resizeLabel = 'Resize sidebar',
  children,
}: SidebarShellProps) {
  const { isMacOverlay } = usePlatform()
  const preset = useMotionPreset()
  const sidebarWidth = useUIStore((state) => state.sidebarWidth)
  const setSidebarWidth = useUIStore((state) => state.setSidebarWidth)
  const resetSidebarWidth = useUIStore((state) => state.resetSidebarWidth)
  const [isResizing, setIsResizing] = useState(false)

  const startResize = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (collapsed || event.pointerType === 'touch') return
    event.preventDefault()
    const startX = event.clientX
    const startWidth = sidebarWidth
    setIsResizing(true)

    const handleMove = (moveEvent: PointerEvent) => {
      setSidebarWidth(startWidth + moveEvent.clientX - startX)
    }
    const handleUp = () => {
      window.removeEventListener('pointermove', handleMove)
      window.removeEventListener('pointerup', handleUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      setIsResizing(false)
    }

    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', handleMove)
    window.addEventListener('pointerup', handleUp, { once: true })
  }, [collapsed, setSidebarWidth, sidebarWidth])

  // On macOS Tauri the rail widens to 70px (matching
  // --spacing-mac-traffic-inset) so the traffic-light buttons land fully
  // inside it instead of spilling into the main content.
  const width = collapsed ? (isMacOverlay ? 70 : 56) : sidebarWidth

  return (
    <motion.aside
      initial={false}
      animate={{ width }}
      transition={isResizing ? { duration: 0 } : preset.transition}
      className="relative flex h-full shrink-0 flex-col overflow-hidden"
      style={{ minWidth: width }}
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
      <div className="flex h-full flex-col gap-1 overflow-hidden p-1">
        {collapsed ? rail : children}
      </div>
    </motion.aside>
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
      className={cn(
        'flex min-h-0 flex-col overflow-hidden rounded-[10px] bg-(--bg-sidebar)/80 shadow-sm backdrop-blur-xl',
        className,
      )}
    >
      {children}
    </div>
  )
}

/** In-card section separator (the forge pattern: a hairline inset by mx-3,
 *  mx-2 in the icon rail) — preferred over `border-t` on the section. */
export function SidebarShellDivider({ className }: { className?: string }) {
  return (
    <div className={cn('shrink-0 h-px bg-(--color-border)', className ?? 'mx-3')} />
  )
}

/**
 * Fake search input that opens the command palette (Ctrl+P). Canonical
 * background is `bg-(--bg-page)` (the forge/aim variant).
 */
export function SidebarSearchTrigger({
  onClick,
}: {
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex h-8 w-full items-center gap-2 rounded-md border border-(--color-border) bg-(--bg-page) px-2.5 text-left text-xs text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
      aria-label="Open command palette"
      title="Open command palette (Ctrl+P)"
    >
      <Search size={13} aria-hidden="true" />
      <span className="flex-1">Search…</span>
      <kbd className="font-mono text-xs text-(--color-text-subtle)">^P</kbd>
    </button>
  )
}

interface SidebarFooterProps {
  /** Opens the command palette; also gates the Help button's visibility. */
  onCommandPalette?: () => void
  /** Icon-rail variant: vertical stack (Settings · Help · theme · health). */
  collapsed?: boolean
  /** Runs after the Settings action (e.g. close the mobile drawer). */
  onAction?: () => void
}

/** Footer trio — Settings + Help | HealthDot + ThemeToggle. */
export function SidebarFooter({
  onCommandPalette,
  collapsed = false,
  onAction,
}: SidebarFooterProps) {
  const openSettings = () => {
    useUIStore.getState().openSettings()
    onAction?.()
  }

  if (collapsed) {
    return (
      <div className="flex w-full shrink-0 flex-col items-center gap-1 px-1 py-2">
        <button
          type="button"
          onClick={openSettings}
          className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
          aria-label="Settings"
          title="Settings"
        >
          <Settings size={14} aria-hidden="true" />
        </button>
        {onCommandPalette && (
          <button
            type="button"
            onClick={onCommandPalette}
            className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Help and shortcuts"
            title="Help and shortcuts (Ctrl+P)"
          >
            <HelpCircle size={14} aria-hidden="true" />
          </button>
        )}
        <ThemeToggle collapsed />
        <HealthDot />
      </div>
    )
  }

  return (
    <div className="flex shrink-0 items-center justify-between gap-2 px-3 py-2 pb-safe">
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={openSettings}
          className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
          aria-label="Settings"
          title="Settings"
        >
          <Settings size={14} aria-hidden="true" />
        </button>
        {onCommandPalette && (
          <button
            type="button"
            onClick={onCommandPalette}
            className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Help and shortcuts"
            title="Help and shortcuts (Ctrl+P)"
          >
            <HelpCircle size={14} aria-hidden="true" />
          </button>
        )}
      </div>
      <div className="flex items-center gap-2">
        <HealthDot />
        <ThemeToggle collapsed />
      </div>
    </div>
  )
}
