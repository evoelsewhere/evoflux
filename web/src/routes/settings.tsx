/**
 * Settings shell — responsive two-column layout below a shared header.
 *
 * Desktop (≥768px):  floating-block layout with 4 px inset + 2 px gaps.
 *   ┌──────────────────────────────────────────────────────┐
 *   │ AppHeader  Home › Settings › Agents        ● local   │
 *   ├──────────────┬───────────────────────────────────────┤
 *   │ Sidebar      │ Detail / list / editor (Outlet)       │
 *   │ (240 px)     │                                       │
 *   └──────────────┴───────────────────────────────────────┘
 *
 * Mobile (<768px):
 *   ┌──────────────────────────────────────────────────────┐
 *   │ AppHeader                                             │
 *   ├──────────────────────────────────────────────────────┤
 *   │ Outlet — full width                                   │
 *   └──────────────────────────────────────────────────────┘
 */
import { Link, Outlet, useLocation } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { Home, Menu } from 'lucide-react'

import { Breadcrumb, type BreadcrumbItem } from '@/components/Breadcrumb'
import { SettingsSidebar } from '@/components/settings/SettingsSidebar'
import { useIsMobile } from '@/hooks/use-mobile'
import { usePlatform } from '@/hooks/use-platform'
import { useTauriDrag } from '@/hooks/use-tauri-drag'

/** Page title shown in the AppHeader based on the current pathname. */
function pageTitleFor(pathname: string): string {
  if (pathname.startsWith('/settings/agents')) return 'Agents'
  if (pathname.startsWith('/settings/skills')) return 'Skills'
  if (pathname.startsWith('/settings/mcp')) return 'MCP servers'
  if (pathname === '/settings/providers') return 'Providers'
  if (pathname === '/settings/multimodal') return 'Multimodal'
  if (pathname === '/settings/sandbox') return 'Sandbox'
  if (pathname === '/settings/dream') return 'Dream'
  if (pathname === '/settings/notifications') return 'Notifications'
  return 'Settings'
}

/** Breadcrumb trail for the current settings page. */
function breadcrumbsFor(pathname: string): BreadcrumbItem[] {
  const section = pageTitleFor(pathname)
  if (section === 'Settings') return [{ label: 'Settings' }]
  return [
    { label: 'Settings', to: '/settings' },
    { label: section },
  ]
}

const ICON_BTN =
  'flex h-9 w-9 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) md:h-7 md:w-7'

export function SettingsLayout() {
  const { pathname } = useLocation()
  const isMobile = useIsMobile()
  const { isMacOverlay } = usePlatform()
  const dragHandlers = useTauriDrag()
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)

  useEffect(() => {
    if (!isMacOverlay) return
    document.documentElement.setAttribute('data-platform', 'mac-overlay')
    return () => document.documentElement.removeAttribute('data-platform')
  }, [isMacOverlay])

  return (
    <div className="mobile-safe-shell mobile-viewport flex h-dvh flex-col overflow-hidden bg-(--bg-page) text-(--color-text) md:gap-0.5 md:p-1">
      {/* Header — disconnected pills matching TeamChatView */}
      <header
        {...dragHandlers}
        className={`mobile-safe-header relative z-20 flex shrink-0 items-center gap-1.5 px-1.5 py-1.5${
          isMacOverlay ? ' select-none' : ''
        }`}
        style={isMacOverlay ? { paddingLeft: 'calc(var(--spacing-mac-traffic-inset) + 6px)' } : undefined}
      >
        {/* Left pill */}
        <div
          className={`flex items-center gap-1 ${
            isMobile
              ? 'flex-1'
              : 'shrink-0 rounded-[10px] bg-(--bg-sidebar)/80 px-2.5 py-1.5 shadow-sm backdrop-blur-xl'
          }`}
        >
          {!isMobile && (
            <Link to="/" aria-label="Home" title="Home" className={ICON_BTN}>
              <Home size={14} aria-hidden="true" />
            </Link>
          )}
          {isMobile && (
            <button
              type="button"
              onClick={() => setMobileSidebarOpen((v) => !v)}
              aria-label="Open settings navigation"
              className={ICON_BTN}
            >
              <Menu size={14} aria-hidden="true" />
            </button>
          )}
          {!isMobile && <Breadcrumb items={breadcrumbsFor(pathname)} />}
          {isMobile && (
            <span className="min-w-0 truncate text-sm font-semibold text-(--color-text)">
              {pageTitleFor(pathname)}
            </span>
          )}
        </div>

        <div className="flex-1" />

        {/* Right pill — connection status */}
        <div className="flex shrink-0 items-center gap-1.5 rounded-[10px] bg-(--bg-sidebar)/80 px-3 py-2 shadow-sm backdrop-blur-xl">
          <span aria-hidden="true" className="h-2 w-2 rounded-full bg-(--color-success)" />
          <span className="font-mono text-[11px] text-(--color-text-muted)">local</span>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 overflow-hidden md:gap-0.5">
        {/* Desktop sidebar — always visible. Mobile renders the same
            sidebar inside a slide-over so the hamburger has somewhere
            meaningful to open. */}
        {!isMobile && <SettingsSidebar />}

        {isMobile && mobileSidebarOpen && (
          <>
            <div
              className="mobile-safe-overlay fixed inset-0 z-30 bg-(--color-overlay)"
              onClick={() => setMobileSidebarOpen(false)}
              aria-hidden="true"
            />
            <div className="mobile-safe-top fixed bottom-0 left-0 z-40 flex">
              <SettingsSidebar />
            </div>
          </>
        )}

        <main id="main" className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-[10px] bg-(--bg-page) md:shadow-sm">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
