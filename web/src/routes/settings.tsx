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
import { useEffect, useRef, useState } from 'react'
import { Menu, X } from 'lucide-react'

import { Breadcrumb, type BreadcrumbItem } from '@/components/Breadcrumb'
import { SettingsSidebar } from '@/components/settings/SettingsSidebar'
import { useIsMobile } from '@/hooks/use-mobile'

/** Sections that own a list page plus per-item editor routes. */
const LIST_SECTIONS: ReadonlyArray<{ segment: string; label: string }> = [
  { segment: 'agents', label: 'Agents' },
  { segment: 'skills', label: 'Skills' },
  { segment: 'mcp', label: 'MCP servers' },
]

const LEAF_SECTIONS: Readonly<Record<string, string>> = {
  providers: 'Providers',
  connection: 'Connection',
  sandbox: 'Sandbox',
  dream: 'Dream',
  notifications: 'Notifications',
  appearance: 'Appearance',
  telemetry: 'Telemetry',
  diagnostics: 'Diagnostics',
}

function sectionFor(pathname: string): { label: string; segment: string; item?: string } | null {
  const parts = pathname.replace(/^\/settings\/?/, '').split('/').filter(Boolean)
  const [segment, ...rest] = parts
  if (!segment) return null

  const list = LIST_SECTIONS.find((entry) => entry.segment === segment)
  if (list) {
    const item = rest.join('/')
    return { label: list.label, segment, item: item === 'new' ? 'New' : item || undefined }
  }

  const leaf = LEAF_SECTIONS[segment]
  return leaf ? { label: leaf, segment } : null
}

/**
 * Breadcrumb trail. On editor routes the section crumb stays a link, which is
 * the only way back to the list on desktop — the page header shows its back
 * button on mobile only.
 */
function breadcrumbsFor(pathname: string): BreadcrumbItem[] {
  const section = sectionFor(pathname)
  if (!section) return [{ label: 'Settings' }]
  const trail: BreadcrumbItem[] = [
    { label: 'Settings', to: '/settings' },
    { label: section.label, to: `/settings/${section.segment}` },
  ]
  if (section.item) trail.push({ label: section.item })
  return trail
}

export function SettingsLayout() {
  const { pathname } = useLocation()
  const isMobile = useIsMobile()
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const dialogRef = useRef<HTMLDivElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    closeButtonRef.current?.focus()

    const handler = (e: KeyboardEvent) => {
      const dialog = dialogRef.current
      if (!dialog || e.defaultPrevented) return

      const openDialogs = Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"]'))
      if (openDialogs.at(-1) !== dialog) return

      if (e.key === 'Escape') {
        e.preventDefault()
        if (mobileSidebarOpen) {
          setMobileSidebarOpen(false)
          return
        }
        window.history.back()
        return
      }

      if (e.key === 'Tab') {
        const focusable = Array.from(
          dialog.querySelectorAll<HTMLElement>(
            'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
          ),
        ).filter((element) => !element.hasAttribute('hidden') && element.getAttribute('aria-hidden') !== 'true')
        if (focusable.length === 0) {
          e.preventDefault()
          dialog.focus()
          return
        }
        const first = focusable[0]
        const last = focusable.at(-1)
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          last?.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => {
      window.removeEventListener('keydown', handler)
      previouslyFocused?.focus()
    }
  }, [mobileSidebarOpen])

  const handleClose = () => window.history.back()

  return (
    <div
      ref={dialogRef}
      tabIndex={-1}
      className="fixed inset-0 z-(--z-modal) flex items-center justify-center bg-(--color-overlay) p-0 backdrop-blur-[2px] md:p-8"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-dialog-title"
      onClick={handleClose}
    >
      <div
        className="flex h-[100dvh] w-full flex-col overflow-hidden bg-(--bg-page) shadow-2xl md:h-[min(90dvh,800px)] md:max-w-6xl md:rounded-2xl md:border md:border-(--color-border)"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <header className="flex min-h-14 shrink-0 items-center gap-2 border-b border-(--color-border) bg-(--bg-card)/70 px-3 pt-[env(safe-area-inset-top)] backdrop-blur-xl md:px-4 md:pt-0">
          {isMobile && (
            <button
              type="button"
              onClick={() => setMobileSidebarOpen((v) => !v)}
              aria-label="Open settings navigation"
              className="flex size-11 items-center justify-center rounded-lg text-(--color-text-muted) transition-[background-color,color,transform] duration-200 hover:bg-(--bg-key) hover:text-(--color-text) active:scale-[0.96]"
            >
              <Menu size={14} aria-hidden="true" />
            </button>
          )}
          {!isMobile && <Breadcrumb items={breadcrumbsFor(pathname)} />}
          {isMobile && (
            <h2 id="settings-dialog-title" className="min-w-0 flex-1 truncate text-sm font-semibold text-(--color-text)">
              Settings
            </h2>
          )}
          {!isMobile && <h2 id="settings-dialog-title" className="sr-only">Settings</h2>}
          {!isMobile && <div className="flex-1" />}
          <button
            type="button"
            ref={closeButtonRef}
            onClick={handleClose}
            aria-label="Close settings"
            title="Close (Esc)"
            className="flex size-11 items-center justify-center rounded-lg text-(--color-text-muted) transition-[background-color,color,transform] duration-200 hover:bg-(--bg-key) hover:text-(--color-text) active:scale-[0.96] md:size-9"
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
                className="fixed inset-0 z-(--z-drawer) bg-(--color-overlay)"
                onClick={() => setMobileSidebarOpen(false)}
                aria-hidden="true"
              />
              <div className="fixed inset-y-0 left-0 z-(--z-overlay) flex p-2 pt-[max(0.5rem,env(safe-area-inset-top))]">
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
