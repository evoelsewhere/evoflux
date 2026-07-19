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
import { PanelLeft } from 'lucide-react'
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts'
import { useUIStore } from '@/stores/useUIStore'

interface AppShellProps {
  sidebar?: ReactNode
  mobileSidebar?: ReactNode
  header?: ReactNode
  trailing?: ReactNode
  overlay?: ReactNode
  /** Forwarded to <main> (TeamChatView anchors the floating input bar on it). */
  mainId?: string
  mainRef?: Ref<HTMLDivElement>
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
  overlay,
  mainId,
  mainRef,
  onTouchStart,
  onTouchMove,
  onTouchEnd,
  onTouchCancel,
  children,
}: AppShellProps) {
  const toggleSidebarCollapsed = useUIStore((s) => s.toggleSidebarCollapsed)
  const hasSidebar = sidebar != null

  // Ctrl+B — the single shell-level sidebar toggle. See the file header for
  // why registration is gated on this shell having a sidebar.
  useKeyboardShortcuts({ b: hasSidebar ? toggleSidebarCollapsed : undefined })

  return (
    // h-dvh handles iOS Safari's dynamic toolbar.
    <div
      className="mobile-safe-shell mobile-viewport flex h-dvh flex-col bg-(--bg-page) md:flex-row md:gap-0.5 md:p-1"
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
      onTouchCancel={onTouchCancel}
    >
      {sidebar}

      {/* Sidebar toggle — same placement + affordance in every mode. */}
      {hasSidebar && (
        <div className="flex shrink-0 flex-col items-center pt-2">
          <button
            type="button"
            onClick={toggleSidebarCollapsed}
            aria-label="Toggle sidebar"
            title="Toggle sidebar (Ctrl+B)"
            className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
          >
            <PanelLeft size={15} aria-hidden="true" />
          </button>
        </div>
      )}

      {/* Right column — optional header + the body row. */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {header}
        <div className="flex min-h-0 flex-1 overflow-hidden">
          {mobileSidebar}
          <main
            id={mainId}
            ref={mainRef}
            className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-[10px] bg-(--bg-page) shadow-sm"
          >
            {children}
          </main>
          {trailing}
        </div>
        {overlay}
      </div>
    </div>
  )
}
