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
import { Outlet, useLocation, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { AppHeader } from '@/components/AppHeader'
import { SettingsSidebar } from '@/components/settings/SettingsSidebar'
import { useIsMobile } from '@/hooks/use-mobile'
import type { BreadcrumbItem } from '@/components/Breadcrumb'

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

export function SettingsLayout() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const isMobile = useIsMobile()
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)

  const handleToggleSidebar = () => {
    if (isMobile) {
      setMobileSidebarOpen((v) => !v)
    } else {
      navigate({ to: '/settings' })
    }
  }

  return (
    <div className="mobile-safe-shell mobile-viewport flex h-dvh flex-col overflow-hidden bg-(--bg-page) text-(--color-text) md:gap-0.5 md:p-1">
      <AppHeader
        title={isMobile ? pageTitleFor(pathname) : undefined}
        onToggleSidebar={handleToggleSidebar}
        breadcrumbs={!isMobile ? breadcrumbsFor(pathname) : undefined}
      />

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

        <main id="main" className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-[10px] bg-(--bg-card) md:shadow-sm">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
