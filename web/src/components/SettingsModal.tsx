/**
 * SettingsModal — renders settings as a popup modal over the current page.
 * Uses useUIStore for open/close and internal path navigation.
 */
import { useEffect, useCallback, useMemo } from 'react'
import { Menu, X } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'

import { useUIStore } from '@/stores/useUIStore'
import { useIsMobile } from '@/hooks/use-mobile'
import { useReducedMotion } from '@/hooks/useReducedMotion'
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
import { LoopSettingsPage } from '@/routes/settings.loop'
import { NotificationSettingsPage } from '@/routes/settings.notifications'
import { BackendConnectionPage } from '@/routes/settings.connection'
import { DiagnosticsPage } from '@/routes/settings.diagnostics'

function pageTitleFor(path: string): string {
  if (path.startsWith('agents')) return 'Agents'
  if (path.startsWith('skills')) return 'Skills'
  if (path.startsWith('mcp')) return 'MCP servers'
  if (path === 'connection') return 'Connection'
  if (path === 'providers') return 'Providers'
  if (path === 'sandbox') return 'Sandbox'
  if (path === 'dream') return 'Dream'
  if (path === 'loop') return 'Loop'
  if (path === 'notifications') return 'Notifications'
  if (path === 'diagnostics') return 'Diagnostics'
  return 'Settings'
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
  if (section === 'loop') return <LoopSettingsPage />
  if (section === 'notifications') return <NotificationSettingsPage />
  if (section === 'diagnostics') return <DiagnosticsPage />
  return <SettingsHubPage />
}

export function SettingsModal() {
  const settingsOpen = useUIStore((s) => s.settingsOpen)
  const settingsPath = useUIStore((s) => s.settingsPath)
  const settingsSearch = useUIStore((s) => s.settingsSearch)
  const closeSettings = useUIStore((s) => s.closeSettings)
  const navigateSettings = useUIStore((s) => s.navigateSettings)
  const isMobile = useIsMobile()
  const prefersReducedMotion = useReducedMotion()

  // Close on Escape
  useEffect(() => {
    if (!settingsOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        closeSettings()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
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

  const handleSidebarNavigate = useCallback((path: string) => {
    // Convert "/settings/agents" → "agents", "/settings" → ""
    const stripped = path.replace(/^\/settings\/?/, '')
    navigateSettings(stripped)
  }, [navigateSettings])

  return (
    <AnimatePresence>
      {settingsOpen && (
        <motion.div
          key="settings-modal"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: prefersReducedMotion ? 0.01 : 0.15 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-(--color-overlay) p-4 md:p-8"
          role="dialog"
          aria-modal="true"
          aria-label="Settings"
          onClick={closeSettings}
        >
          <motion.div
            initial={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, scale: 0.96 }}
            animate={prefersReducedMotion ? { opacity: 1 } : { opacity: 1, scale: 1 }}
            exit={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, scale: 0.96 }}
            transition={{ duration: prefersReducedMotion ? 0.01 : 0.15 }}
            className="flex h-full w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-page) shadow-2xl md:h-[min(85vh,720px)] md:w-full"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <header className="flex shrink-0 items-center gap-2 border-b border-(--color-border) px-4 py-3">
              {isMobile && (
                <button
                  type="button"
                  aria-label="Open settings navigation"
                  className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                >
                  <Menu size={14} aria-hidden="true" />
                </button>
              )}
              <span className="min-w-0 flex-1 text-sm font-semibold text-(--color-text)">
                {pageTitleFor(settingsPath)}
              </span>
              <button
                type="button"
                onClick={closeSettings}
                aria-label="Close settings"
                title="Close (Esc)"
                className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
              >
                <X size={16} aria-hidden="true" />
              </button>
            </header>

            {/* Body */}
            <div className="flex min-h-0 flex-1 overflow-hidden">
              {!isMobile && (
                <SettingsSidebar
                  currentPath={fullPath}
                  onNavigate={handleSidebarNavigate}
                />
              )}
              <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">
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
