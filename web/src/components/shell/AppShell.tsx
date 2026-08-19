/**
 * AppShell — the unified desktop frame shared by every top-level mode
 * layout (TeamChatView for work/coding). It owns the chrome those layouts
 * used to hand-mirror in each other:
 *   - the outer full-viewport container (mobile-safe, h-dvh, md row layout)
 *   - the sidebar slot + the sidebar-toggle button between sidebar and main
 *   - the <main> content card (rounded, shadowed)
 *
 * Collapse state lives in useUIStore (``sidebarCollapsed``, persisted as
 * "oa-sidebar-collapsed"); the mode sidebars read it directly, so the
 * toggle button just fires the store action.
 *
 * Ctrl+B is registered HERE, exactly once per rendered shell, and only when
 * the shell actually renders a sidebar.
 *
 * Slots:
 *   sidebar       — desktop sidebar instance (the caller mode-selects it);
 *                   null/undefined → no sidebar and no toggle button.
 *   mobileSidebar — mobile/responsive overlay drawer, rendered at shell level
 *                   so it remains available over a maximized Workbench.
 *   header        — optional strip above the body row (TeamChatView).
 *   trailing      — panels rendered after <main> inside the body row.
 *   overlay       — panels rendered after the body row (modals, palette).
 *   children      — the main content.
 */

import { useEffect, type ReactNode, type Ref, type TouchEventHandler } from 'react'
import { motion } from 'framer-motion'
import { PanelLeft } from 'lucide-react'
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts'
import { usePlatform } from '@/hooks/use-platform'
import { useMotionPreset } from '@/lib/motion'
import { useUIStore } from '@/stores/useUIStore'
import { formatShortcutLabel } from '@/lib/keyboard-shortcuts'
import { SHELL_SIDEBAR_TOGGLE_EVENT } from '@/lib/shell-events'

interface AppShellProps {
  sidebar?: ReactNode
  mobileSidebar?: ReactNode
  /** Desktop navigation is temporarily rendered as a non-layout drawer. */
  sidebarOverlay?: boolean
  /** Toggle the responsive desktop navigation drawer (also used by Ctrl+B). */
  onToggleSidebarOverlay?: () => void
  header?: ReactNode
  trailing?: ReactNode
  fullHeightTrailing?: ReactNode
  overlay?: ReactNode
  /** Forwarded to <main> (TeamChatView anchors the floating input bar on it). */
  mainId?: string
  mainRef?: Ref<HTMLDivElement>
  /** Hide the conversation canvas while a workbench tool is maximized. */
  mainHidden?: boolean
  onTouchStart?: TouchEventHandler<HTMLDivElement>
  onTouchMove?: TouchEventHandler<HTMLDivElement>
  onTouchEnd?: TouchEventHandler<HTMLDivElement>
  onTouchCancel?: TouchEventHandler<HTMLDivElement>
  children: ReactNode
}

export function AppShell({
  sidebar,
  mobileSidebar,
  sidebarOverlay = false,
  onToggleSidebarOverlay,
  header,
  trailing,
  fullHeightTrailing,
  overlay,
  mainId,
  mainRef,
  mainHidden = false,
  onTouchStart,
  onTouchMove,
  onTouchEnd,
  onTouchCancel,
  children,
}: AppShellProps) {
  const sidebarCollapsed = useUIStore((s) => s.sidebarCollapsed)
  const toggleSidebarCollapsed = useUIStore((s) => s.toggleSidebarCollapsed)
  const hasDockedSidebar = sidebar != null
  const hasResponsiveSidebar = mobileSidebar != null
  const toggleSidebar = sidebarOverlay || (!hasDockedSidebar && hasResponsiveSidebar)
    ? onToggleSidebarOverlay
    : hasDockedSidebar
      ? toggleSidebarCollapsed
      : undefined
  const motionPreset = useMotionPreset()
  const { isMacOverlay } = usePlatform()

  // Ctrl+B — the single shell-level sidebar toggle. See the file header for
  // why registration is gated on this shell having a sidebar.
  useKeyboardShortcuts({ b: toggleSidebar })

  // macOS renders the sidebar affordance beside the native traffic lights.
  // Keep the action inside AppShell so adaptive drawer state remains local to
  // TeamChatView and the title bar never needs feature-specific callbacks.
  useEffect(() => {
    if (!isMacOverlay || !toggleSidebar) return
    const handleToggle = () => toggleSidebar()
    window.addEventListener(SHELL_SIDEBAR_TOGGLE_EVENT, handleToggle)
    return () => window.removeEventListener(SHELL_SIDEBAR_TOGGLE_EVENT, handleToggle)
  }, [isMacOverlay, toggleSidebar])

  return (
    // h-dvh handles iOS Safari's dynamic toolbar.
    <div
      data-app-shell
      className="mobile-safe-shell mobile-viewport relative flex h-dvh flex-col bg-(--bg-page) md:flex-row md:gap-0.5 md:p-0.5"
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
      onTouchCancel={onTouchCancel}
    >
      {sidebar}
      {mobileSidebar}

      {/* Sidebar toggle — same placement + affordance in every mode. */}
      {hasDockedSidebar && !isMacOverlay && (
        <div
          className={
            sidebarCollapsed
              ? 'pointer-events-none absolute top-2 z-(--z-header) flex flex-col items-center'
              : 'flex shrink-0 flex-col items-center pt-2'
          }
          style={sidebarCollapsed
            ? { left: 4 }
            : undefined}
        >
          <motion.button
            type="button"
            onClick={toggleSidebarCollapsed}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.9 }}
            transition={motionPreset.spring}
            aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!sidebarCollapsed}
            title={`Toggle sidebar (${formatShortcutLabel('Ctrl+B')})`}
            className="pointer-events-auto flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            data-no-drag
          >
            <PanelLeft size={15} aria-hidden="true" />
          </motion.button>
        </div>
      )}

      {/* Right column — optional header + the body row. */}
      <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
        <div
          className={
            mainHidden
              ? 'hidden'
              : 'flex min-h-0 min-w-0 flex-1 flex-col'
          }
        >
          {header}
          <div className="flex min-h-0 flex-1 overflow-hidden">
            <motion.main
              key="app-main-canvas"
              id={mainId}
              ref={mainRef}
              initial={{ opacity: 0, scale: 0.995 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={motionPreset.transition}
              className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-md bg-(--bg-page)"
            >
              {children}
            </motion.main>
            {trailing}
          </div>
          {overlay}
        </div>
        {fullHeightTrailing}
      </div>
    </div>
  )
}
