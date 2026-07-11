/**
 * Settings modal — renders as a full-screen overlay dialog on top of
 * whatever page the user was on (forge / coding). Deep-links still work.
 *
 * Desktop (≥768px):  centered modal with sidebar + outlet.
 *   ┌──────────────────────────────────────────────────────┐
 *   │ ░░░░░░░░░░░░░ overlay backdrop ░░░░░░░░░░░░░░░░░░░░ │
 *   │ ░┌────────────────────────────────────────────────┐░ │
 *   │ ░│ Header  Settings › Agents              [×]     │░ │
 *   │ ░├──────────────┬─────────────────────────────────┤░ │
 *   │ ░│ Sidebar      │ Detail / list / editor (Outlet) │░ │
 *   │ ░│ (220 px)     │                                 │░ │
 *   │ ░└──────────────┴─────────────────────────────────┘░ │
 *   └──────────────────────────────────────────────────────┘
 *
 * Mobile (<768px): full-screen modal with hamburger nav.
 */
import { Outlet, useLocation } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { Menu, X } from 'lucide-react'

import { Breadcrumb, type BreadcrumbItem } from '@/components/Breadcrumb'
import { SettingsSidebar } from '@/components/settings/SettingsSidebar'
import { useIsMobile } from '@/hooks/use-mobile'

/** Page title shown in the modal header based on the current pathname. */
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
  const isMobile = useIsMobile()
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        window.history.back()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const handleClose = () => window.history.back()

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-(--color-overlay) p-4 md:p-8"
      role="dialog"
      aria-modal="true"
      aria-label="Settings"
      onClick={handleClose}
    >
      <div
        className="flex h-full w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-page) shadow-2xl md:h-[min(85vh,720px)] md:w-full"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <header className="flex shrink-0 items-center gap-2 border-b border-(--color-border) px-4 py-3">
          {isMobile && (
            <button
              type="button"
              onClick={() => setMobileSidebarOpen((v) => !v)}
              aria-label="Open settings navigation"
              className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            >
              <Menu size={14} aria-hidden="true" />
            </button>
          )}
          {!isMobile && <Breadcrumb items={breadcrumbsFor(pathname)} />}
          {isMobile && (
            <span className="min-w-0 flex-1 truncate text-sm font-semibold text-(--color-text)">
              {pageTitleFor(pathname)}
            </span>
          )}
          {!isMobile && <div className="flex-1" />}
          <button
            type="button"
            onClick={handleClose}
            aria-label="Close settings"
            title="Close (Esc)"
            className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </header>

        {/* Body */}
        <div className="flex min-h-0 flex-1 overflow-hidden">
          {!isMobile && <SettingsSidebar />}

          {isMobile && mobileSidebarOpen && (
            <>
              <div
                className="fixed inset-0 z-30 bg-(--color-overlay)"
                onClick={() => setMobileSidebarOpen(false)}
                aria-hidden="true"
              />
              <div className="fixed bottom-0 left-0 top-0 z-40 flex">
                <SettingsSidebar />
              </div>
            </>
          )}

          <main id="main" className="flex min-w-0 flex-1 flex-col overflow-hidden">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  )
}
