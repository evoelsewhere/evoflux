/**
 * SettingsModal — renders settings as a popup modal over the current page.
 * Uses useUIStore for open/close and internal path navigation.
 */
import { useEffect, useCallback, useMemo, useRef } from 'react'
import { ChevronRight, X } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'

import { useUIStore } from '@/stores/useUIStore'
import { useIsMobile } from '@/hooks/use-mobile'
import { useMotionPreset } from '@/lib/motion'
import { SettingsSidebar } from '@/components/settings/SettingsSidebar'
import { SettingsProvider } from '@/contexts/SettingsContext'
import { SettingsHubPage } from '@/routes/settings.index'
import { AgentsListPage } from '@/routes/settings.agents'
import { AgentEditorPage } from '@/routes/settings.agents.$name'
import { NewAgentPage } from '@/routes/settings.agents.new'
import { SkillsListPage } from '@/routes/settings.skills'
import { SkillEditorPage } from '@/routes/settings.skills.$name'
import { NewSkillPage } from '@/routes/settings.skills.new'
import { McpListPage } from '@/routes/settings.mcp'
import { NewMcpServerPage } from '@/routes/settings.mcp.new'
import { McpServerDetailPage } from '@/routes/settings.mcp.$name'
import { SandboxSettingsPage } from '@/routes/settings.sandbox'
import { ProvidersSettingsPage } from '@/routes/settings.providers'
import { DreamSettingsPage } from '@/routes/settings.dream'
import { NotificationSettingsPage } from '@/routes/settings.notifications'
import { AppearanceSettingsPage } from '@/routes/settings.appearance'
import { BackendConnectionPage } from '@/routes/settings.connection'
import { DiagnosticsPage } from '@/routes/settings.diagnostics'
import { TelemetrySettingsPage } from '@/routes/settings.telemetry'

/** Sections that own a list page plus per-item editor routes. */
const LIST_SECTIONS: Readonly<Record<string, string>> = {
  agents: 'Agents',
  skills: 'Skills',
  mcp: 'MCP servers',
}

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

interface Crumb {
  label: string
  /** Store path to navigate to. Omitted for the current, non-clickable crumb. */
  to?: string
}

/**
 * Trail for the modal header. On editor paths the section crumb stays
 * clickable, which is the only way back to the list on desktop — the page
 * header renders its back button on mobile only.
 */
function crumbsFor(path: string): Crumb[] {
  const [section, ...rest] = path.split('/').filter(Boolean)
  if (!section) return [{ label: 'Settings' }]

  const listLabel = LIST_SECTIONS[section]
  if (listLabel) {
    const item = rest.join('/')
    const trail: Crumb[] = [{ label: 'Settings', to: '' }]
    if (item) {
      trail.push({ label: listLabel, to: section })
      trail.push({ label: item === 'new' ? 'New' : item })
    } else {
      trail.push({ label: listLabel })
    }
    return trail
  }

  const leafLabel = LEAF_SECTIONS[section]
  if (!leafLabel) return [{ label: 'Settings' }]
  return [{ label: 'Settings', to: '' }, { label: leafLabel }]
}

function SettingsContent({ path }: { path: string }) {
  // Extract name param from paths like "agents/lead" or "mcp/my-server"
  const parts = path.split('/')
  const section = parts[0] || ''
  const sub = parts[1] || ''

  if (section === 'agents' && sub === 'new') return <NewAgentPage />
  if (section === 'agents' && sub) return <AgentEditorPage />
  if (section === 'agents') return <AgentsListPage />
  if (section === 'skills' && sub === 'new') return <NewSkillPage />
  if (section === 'skills' && sub) return <SkillEditorPage />
  if (section === 'skills') return <SkillsListPage />
  if (section === 'mcp' && sub === 'new') return <NewMcpServerPage />
  if (section === 'mcp' && sub) return <McpServerDetailPage />
  if (section === 'mcp') return <McpListPage />
  if (section === 'connection') return <BackendConnectionPage />
  if (section === 'providers') return <ProvidersSettingsPage />
  if (section === 'sandbox') return <SandboxSettingsPage />
  if (section === 'dream') return <DreamSettingsPage />
  if (section === 'notifications') return <NotificationSettingsPage />
  if (section === 'appearance') return <AppearanceSettingsPage />
  if (section === 'diagnostics') return <DiagnosticsPage />
  if (section === 'telemetry') return <TelemetrySettingsPage />
  return <SettingsHubPage />
}

export function SettingsModal() {
  const settingsOpen = useUIStore((s) => s.settingsOpen)
  const settingsPath = useUIStore((s) => s.settingsPath)
  const settingsSearch = useUIStore((s) => s.settingsSearch)
  const closeSettings = useUIStore((s) => s.closeSettings)
  const navigateSettings = useUIStore((s) => s.navigateSettings)
  const isMobile = useIsMobile()
  const motionPreset = useMotionPreset()
  const dialogRef = useRef<HTMLDivElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!settingsOpen) return
    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    closeButtonRef.current?.focus()

    const handler = (e: KeyboardEvent) => {
      const dialog = dialogRef.current
      if (!dialog || e.defaultPrevented) return
      const dialogs = Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"]'))
      if (dialogs.at(-1) !== dialog) return

      if (e.key === 'Escape') {
        e.preventDefault()
        closeSettings()
        return
      }

      if (e.key === 'Tab') {
        const focusable = Array.from(
          dialog.querySelectorAll<HTMLElement>(
            'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
          ),
        ).filter((element) => !element.hasAttribute('hidden') && element.getAttribute('aria-hidden') !== 'true')
        const first = focusable[0]
        const last = focusable.at(-1)
        if (!first) {
          e.preventDefault()
          dialog.focus()
        } else if (e.shiftKey && document.activeElement === first) {
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
  }, [settingsOpen, closeSettings])

  // Parse params from path (e.g. "agents/lead" → { name: "lead" }, "agents/coding/lead" → { name: "coding/lead" })
  const params = useMemo((): Record<string, string> => {
    const parts = settingsPath.split('/')
    const section = parts[0] || ''
    const sub = parts[1] || ''
    if ((section === 'agents' || section === 'skills' || section === 'mcp') && sub && sub !== 'new') {
      return { name: parts.slice(1).join('/') }
    }
    return {}
  }, [settingsPath])

  // Convert store path to full settings path for sidebar active state
  const fullPath = settingsPath ? `/settings/${settingsPath}` : '/settings'

  const crumbs = useMemo(() => crumbsFor(settingsPath), [settingsPath])

  const handleSidebarNavigate = useCallback((path: string) => {
    // Convert "/settings/agents" → "agents", "/settings" → ""
    const stripped = path.replace(/^\/settings\/?/, '')
    navigateSettings(stripped)
  }, [navigateSettings])

  return (
    <AnimatePresence>
      {settingsOpen && (
        <motion.div
          ref={dialogRef}
          key="settings-modal"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={motionPreset.transition}
          className="fixed inset-0 z-(--z-modal) flex items-center justify-center bg-(--color-overlay) p-0 backdrop-blur-[2px] md:p-3"
          role="dialog"
          aria-modal="true"
          aria-labelledby="settings-dialog-title"
          onClick={closeSettings}
        >
          <motion.div
            tabIndex={-1}
            initial={{ opacity: 0, scale: 1 - 0.04 * motionPreset.distance, y: 6 * motionPreset.distance }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 1 - 0.03 * motionPreset.distance, y: 4 * motionPreset.distance }}
            transition={motionPreset.spring}
            className="flex h-[100dvh] w-full flex-col overflow-hidden bg-(--bg-page) shadow-2xl md:h-[min(94dvh,960px)] md:w-[min(94vw,1600px)] md:max-w-none md:rounded-xl md:border md:border-(--color-border)"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <header className="flex min-h-14 shrink-0 items-center gap-2 border-b border-(--color-border) bg-(--bg-card)/70 px-3 pt-[env(safe-area-inset-top)] backdrop-blur-xl md:min-h-12 md:pt-0">
              {isMobile ? (
                <h2 id="settings-dialog-title" className="min-w-0 flex-1 truncate text-sm font-semibold text-(--color-text)">
                  Settings
                </h2>
              ) : (
                <>
                  <h2 id="settings-dialog-title" className="sr-only">Settings</h2>
                  <nav
                    aria-label="Breadcrumb"
                    className="flex min-w-0 flex-1 items-center gap-0.5 text-xs text-(--color-text-muted)"
                  >
                    {crumbs.map((crumb, index) => {
                      const isLast = index === crumbs.length - 1
                      return (
                        <span key={`${crumb.label}-${index}`} className="flex min-w-0 items-center gap-0.5">
                          {index > 0 && (
                            <ChevronRight size={11} aria-hidden="true" className="shrink-0 opacity-40" />
                          )}
                          {isLast || crumb.to === undefined ? (
                            <span className="min-w-0 truncate px-0.5 font-medium text-(--color-text)" title={crumb.label}>
                              {crumb.label}
                            </span>
                          ) : (
                            <button
                              type="button"
                              onClick={() => navigateSettings(crumb.to ?? '')}
                              className="shrink-0 truncate rounded px-0.5 transition-colors hover:text-(--color-text)"
                            >
                              {crumb.label}
                            </button>
                          )}
                        </span>
                      )
                    })}
                  </nav>
                </>
              )}
              <button
                type="button"
                ref={closeButtonRef}
                onClick={closeSettings}
                aria-label="Close settings"
                title="Close (Esc)"
                className="flex size-11 items-center justify-center rounded-lg text-(--color-text-muted) transition-[background-color,color,transform] duration-200 hover:bg-(--bg-key) hover:text-(--color-text) active:scale-[0.96] md:size-9"
              >
                <X size={16} aria-hidden="true" />
              </button>
            </header>

            {/* Body */}
            <div className="flex min-h-0 flex-1 gap-1.5 overflow-hidden md:p-1.5">
              {!isMobile && (
                <SettingsSidebar
                  currentPath={fullPath}
                  onNavigate={handleSidebarNavigate}
                />
              )}
              <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
                <SettingsProvider path={settingsPath} params={params} search={settingsSearch}>
                  <SettingsContent path={settingsPath} />
                </SettingsProvider>
              </main>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
