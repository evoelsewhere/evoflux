/**
 * SettingsScreen — a page-level settings surface that replaces the active app
 * view while it is open. Navigation remains store-driven so every existing
 * settings entry point can preserve the app route it returns to.
 */
import { useCallback, useEffect, useMemo, useRef } from 'react'
import { ArrowLeft, ChevronRight } from 'lucide-react'

import { SettingsSidebar } from '@/components/settings/SettingsSidebar'
import { SettingsProvider } from '@/contexts/SettingsContext'
import { useIsMobile } from '@/hooks/use-mobile'
import { useTauriDrag } from '@/hooks/use-tauri-drag'
import { useUIStore } from '@/stores/useUIStore'
import { AgentEditorPage } from '@/routes/settings.agents.$name'
import { NewAgentPage } from '@/routes/settings.agents.new'
import { AgentsListPage } from '@/routes/settings.agents'
import { AppearanceSettingsPage } from '@/routes/settings.appearance'
import { BackendConnectionPage } from '@/routes/settings.connection'
import { DiagnosticsPage } from '@/routes/settings.diagnostics'
import { SettingsHubPage } from '@/routes/settings.index'
import { McpServerDetailPage } from '@/routes/settings.mcp.$name'
import { NewMcpServerPage } from '@/routes/settings.mcp.new'
import { McpListPage } from '@/routes/settings.mcp'
import { MemorySettingsPage } from '@/routes/settings.memory'
import { NotificationSettingsPage } from '@/routes/settings.notifications'
import { ProvidersSettingsPage } from '@/routes/settings.providers'
import { SandboxSettingsPage } from '@/routes/settings.sandbox'
import { SkillEditorPage } from '@/routes/settings.skills.$name'
import { NewSkillPage } from '@/routes/settings.skills.new'
import { SkillsListPage } from '@/routes/settings.skills'
import { TelemetrySettingsPage } from '@/routes/settings.telemetry'

const LIST_SECTIONS: Readonly<Record<string, string>> = {
  agents: 'Agents',
  skills: 'Skills',
  mcp: 'MCP servers',
}

const LEAF_SECTIONS: Readonly<Record<string, string>> = {
  providers: 'Providers',
  connection: 'Connection',
  memory: 'Memory',
  sandbox: 'Sandbox',
  notifications: 'Notifications',
  appearance: 'Appearance',
  telemetry: 'Telemetry',
  diagnostics: 'Diagnostics',
}

interface Crumb {
  label: string
  /** Store path to navigate to. Omitted for the current crumb. */
  to?: string
}

function crumbsFor(path: string): Crumb[] {
  const [rawSection, ...rest] = path.split('/').filter(Boolean)
  const section = rawSection === 'dream' ? 'memory' : rawSection
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
  if (section === 'memory') return <MemorySettingsPage />
  if (section === 'connection') return <BackendConnectionPage />
  if (section === 'providers') return <ProvidersSettingsPage />
  if (section === 'sandbox') return <SandboxSettingsPage />
  // Keep old command/deep-link targets working after Dream was folded into Memory.
  if (section === 'dream') return <MemorySettingsPage />
  if (section === 'notifications') return <NotificationSettingsPage />
  if (section === 'appearance') return <AppearanceSettingsPage />
  if (section === 'diagnostics') return <DiagnosticsPage />
  if (section === 'telemetry') return <TelemetrySettingsPage />
  return <SettingsHubPage />
}

export function SettingsScreen() {
  const settingsPath = useUIStore((state) => state.settingsPath)
  const settingsSearch = useUIStore((state) => state.settingsSearch)
  const closeSettings = useUIStore((state) => state.closeSettings)
  const navigateSettings = useUIStore((state) => state.navigateSettings)
  const isMobile = useIsMobile()
  const dragHandlers = useTauriDrag()
  const screenRef = useRef<HTMLElement>(null)

  useEffect(() => {
    screenRef.current?.focus()

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.key !== 'Escape') return
      if (document.querySelector('[role="dialog"]')) return
      event.preventDefault()
      closeSettings()
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [closeSettings])

  const params = useMemo((): Record<string, string> => {
    const parts = settingsPath.split('/')
    const section = parts[0] || ''
    const sub = parts[1] || ''
    if ((section === 'agents' || section === 'skills' || section === 'mcp') && sub && sub !== 'new') {
      return { name: parts.slice(1).join('/') }
    }
    return {}
  }, [settingsPath])

  const crumbs = useMemo(() => crumbsFor(settingsPath), [settingsPath])
  const canonicalSettingsPath =
    settingsPath === 'dream' || settingsPath.startsWith('dream/')
      ? settingsPath.replace(/^dream/, 'memory')
      : settingsPath
  const fullPath = canonicalSettingsPath ? `/settings/${canonicalSettingsPath}` : '/settings'

  const handleSidebarNavigate = useCallback((path: string) => {
    navigateSettings(path.replace(/^\/settings\/?/, ''))
  }, [navigateSettings])

  return (
    <section
      ref={screenRef}
      tabIndex={-1}
      aria-labelledby="settings-screen-title"
      className="mobile-safe-shell mobile-viewport flex h-dvh min-h-0 overflow-hidden bg-(--bg-page) text-(--color-text) outline-none"
    >
      <h1 id="settings-screen-title" className="sr-only">Settings</h1>

      {!isMobile && (
        <SettingsSidebar
          currentPath={fullPath}
          onNavigate={handleSidebarNavigate}
          onBack={closeSettings}
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header
          {...dragHandlers}
          className="mobile-safe-header flex min-h-12 shrink-0 items-center gap-2 border-b border-(--color-border-subtle) bg-(--bg-sidebar)/65 px-3 md:px-5"
        >
          {isMobile && (
            <button
              type="button"
              onClick={closeSettings}
              aria-label="Back to app"
              className="flex size-10 shrink-0 items-center justify-center rounded-lg text-(--color-text-muted) transition-[background-color,color,transform] hover:bg-(--bg-key) hover:text-(--color-text) active:scale-[0.96]"
            >
              <ArrowLeft size={17} aria-hidden="true" />
            </button>
          )}
          <nav
            aria-label="Settings breadcrumb"
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
                    <span className="min-w-0 truncate px-1 font-medium text-(--color-text)" title={crumb.label}>
                      {crumb.label}
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => navigateSettings(crumb.to ?? '')}
                      className="shrink-0 truncate rounded px-1 py-1 transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                    >
                      {crumb.label}
                    </button>
                  )}
                </span>
              )
            })}
          </nav>
        </header>

        <main id="main" className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <SettingsProvider path={settingsPath} params={params} search={settingsSearch}>
            <SettingsContent path={settingsPath} />
          </SettingsProvider>
        </main>
      </div>
    </section>
  )
}
