/**
 * AppShell — the unified desktop frame shared by every top-level mode
 * layout (TeamChatView for forge/coding/aim-chat, routes/aim.tsx for AIM).
 * It owns the chrome those layouts used to hand-mirror in each other:
 *   - the outer full-viewport container (mobile-safe, h-dvh, md row layout)
 *   - the sidebar slot + the sidebar-toggle button between sidebar and main
 *   - the <main> content card (rounded, shadowed)
 *
 * Collapse state lives in useUIStore (``sidebarCollapsed``, persisted as
 * "oa-sidebar-collapsed"); the mode sidebars read it directly, so the
 * toggle button just fires the store action.
 *
 * Ctrl+B is registered HERE, exactly once per rendered shell, and only when
 * the shell actually renders a sidebar. The one nested case is the aim-chat
 * Discussion panel: TeamChatView with mode="aim" mounts inside the AIM
 * layout, so it passes sidebar={null} and leaves Ctrl+B (and the toggle
 * button) to the outer AIM shell — previously both shells' handlers fired.
 *
 * Slots:
 *   sidebar       — desktop sidebar instance (the caller mode-selects it);
 *                   null/undefined → no sidebar and no toggle button.
 *   mobileSidebar — mobile overlay drawer, rendered inside the body row
 *                   for z-stacking (it is position:fixed).
 *   header        — optional strip above the body row (TeamChatView).
 *   trailing      — panels rendered after <main> inside the body row.
 *   overlay       — panels rendered after the body row (modals, palette).
 *   children      — the main content.
 */

import type { ReactNode, Ref, TouchEventHandler } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { PanelLeft } from 'lucide-react'
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts'
import { useMotionPreset } from '@/lib/motion'
import { useUIStore } from '@/stores/useUIStore'

interface AppShellProps {
  sidebar?: ReactNode
  mobileSidebar?: ReactNode
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
  const toggleSidebarCollapsed = useUIStore((s) => s.toggleSidebarCollapsed)
  const hasSidebar = sidebar != null
  const motionPreset = useMotionPreset()

  // Ctrl+B — the single shell-level sidebar toggle. See the file header for
  // why registration is gated on this shell having a sidebar.
  useKeyboardShortcuts({ b: hasSidebar ? toggleSidebarCollapsed : undefined })

  return (
    // h-dvh handles iOS Safari's dynamic toolbar.
    <div
      className="mobile-safe-shell mobile-viewport flex h-dvh flex-col bg-(--bg-page) md:flex-row md:gap-0.5 md:p-0.5"
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
      onTouchCancel={onTouchCancel}
    >
      {sidebar}

      {/* Sidebar toggle — same placement + affordance in every mode. */}
      {hasSidebar && (
        <div className="flex shrink-0 flex-col items-center pt-2">
          <motion.button
            type="button"
            onClick={toggleSidebarCollapsed}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.9 }}
            transition={motionPreset.spring}
            aria-label="Toggle sidebar"
            title="Toggle sidebar (Ctrl+B)"
            className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
          >
            <PanelLeft size={15} aria-hidden="true" />
          </motion.button>
        </div>
      )}

      {/* Right column — optional header + the body row. */}
      <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {header}
          <div className="flex min-h-0 flex-1 overflow-hidden">
            {mobileSidebar}
            <AnimatePresence initial={false} mode="popLayout">
              {!mainHidden && (
                <motion.main
                  key="app-main-canvas"
                  layout="size"
                  id={mainId}
                  ref={mainRef}
                  initial={{ opacity: 0, scale: 0.995 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.99 }}
                  transition={motionPreset.transition}
                  className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-md bg-(--bg-page)"
                >
                  {children}
                </motion.main>
              )}
            </AnimatePresence>
            {trailing}
          </div>
          {overlay}
        </div>
        {fullHeightTrailing}
      </div>
    </div>
  )
}
