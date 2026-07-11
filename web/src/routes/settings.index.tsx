/**
 * /settings — "About EvoFlux" landing.
 *
 * Desktop hides the sidebar category list (the rail already shows them);
 * mobile re-uses this page as the settings hub by rendering nav cards.
 *
 */
import {
  Bell,
  ChevronRight,
  Server,
  Info,
  Image,
  KeyRound,
  Moon,
  Plug,
  Shield,
  Sparkles,
  Wrench,
  type LucideIcon,
} from 'lucide-react'

import { cn } from '@/lib/utils'
import { useIsMobile } from '@/hooks/use-mobile'
import { useSettingsNavigate } from '@/contexts/SettingsContext'
import {
  useAgentFilesQuery,
  useHealthQuery,
  useMcpServersQuery,
  useProvidersQuery,
  useSandboxSettingsQuery,
  useSkillFilesQuery,
} from '@/queries'
import { useUIStore } from '@/stores/useUIStore'

interface CardProps {
  to: string
  icon: LucideIcon
  title: string
  description: string
  count: number | null
  countLabel: string
}

function SettingsNavCard({ to, icon: Icon, title, description, count, countLabel }: CardProps) {
  const navigate = useSettingsNavigate()
  return (
    <button
      type="button"
      onClick={() => navigate(to)}
      className={cn(
        'group flex w-full items-start gap-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4 text-left text-(--color-text) transition-colors sm:items-center sm:gap-4',
        'hover:border-(--color-border-strong) hover:bg-(--color-surface)',
        'focus-visible:border-(--focus-ring) focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-(--focus-ring)/40',
      )}
    >
      <span
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-(--bg-key) text-(--color-text-muted) ring-1 ring-(--color-border) transition-colors group-hover:text-(--color-text)"
        aria-hidden="true"
      >
        <Icon size={18} />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:gap-2">
          <span className="text-sm font-semibold text-(--color-text)">{title}</span>
          <span className="w-fit rounded-md bg-(--bg-key) px-2 py-0.5 font-mono text-xs tabular-nums text-(--color-text-muted)">
            {count === null ? '–' : count} {countLabel}
          </span>
        </div>
        <p className="mt-1 text-xs leading-5 text-(--color-text-muted) sm:truncate">{description}</p>
      </div>

      <ChevronRight
        size={16}
        className="shrink-0 text-(--color-text-muted) transition-transform group-hover:translate-x-0.5 group-hover:text-(--color-text)"
        aria-hidden="true"
      />
    </button>
  )
}

function SectionHeader({ children }: { children: string }) {
  return (
    <h2 className="mb-2 px-1 text-xs font-medium tracking-wider text-(--color-text-muted) uppercase">
      {children}
    </h2>
  )
}

export function SettingsHubPage() {
  const isMobile = useIsMobile()
  const agentsQ = useAgentFilesQuery()
  const skillsQ = useSkillFilesQuery()
  const mcpQ = useMcpServersQuery()
  const providersQ = useProvidersQuery()
  const sandboxQ = useSandboxSettingsQuery()
  const healthQ = useHealthQuery()

  const agentsCount = agentsQ.data?.agents.length ?? null
  const skillsCount = skillsQ.data?.skills.length ?? null
  const mcpCount = mcpQ.data?.servers.length ?? null
  const connectedProvidersCount = providersQ.data?.providers.filter((provider) => provider.is_configured).length ?? null
  const sandboxCount = sandboxQ.data?.denied_patterns.length ?? null
  const version = healthQ.data?.version

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-6 px-3 pt-4 pb-8 sm:space-y-8 sm:px-8 sm:pt-8 sm:pb-12">
        <header className="flex items-center gap-3">
          <span
            className="flex h-10 w-10 items-center justify-center rounded-xl bg-(--bg-key) text-(--color-text-muted) ring-1 ring-(--color-border)"
            aria-hidden="true"
          >
            <Info size={18} />
          </span>
          <div>
            <h1 className="text-lg font-semibold text-(--color-text)">About EvoFlux</h1>
            <p className="text-xs text-(--color-text-muted)">
              {version
                ? `On-machine AI assistant · v${version}`
                : 'On-machine AI assistant'}
            </p>
          </div>
        </header>

        <section className="rounded-md border border-(--color-border) bg-(--bg-card) p-4 shadow-sm">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-(--bg-key) text-(--color-text-muted) ring-1 ring-(--color-border)" aria-hidden="true">
              <Server size={18} />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-sm font-semibold text-(--color-text)">Backend connection</h2>
              <p className="mt-1 text-xs leading-5 text-(--color-text-muted)">
                Connect this app to an existing EvoFlux server, or switch back to the bundled local sidecar when available.
              </p>
            </div>
            <button
              type="button"
              onClick={() => useUIStore.getState().navigateSettings('connection')}
              className="rounded-md border border-(--color-border) px-3 py-1.5 text-xs font-medium text-(--color-text) hover:bg-(--bg-page)"
            >
              Configure
            </button>
          </div>
        </section>

        {/* Mobile picks up navigation from this list because the sidebar is
            hidden on small screens. */}
        {isMobile && (
          <>
            <section>
              <SectionHeader>Workspace</SectionHeader>
              <div className="space-y-2">
                <SettingsNavCard
                  to="/settings/agents"
                  icon={Wrench}
                  title="Agents"
                  description="Define and edit your agent team — model, tools, system prompt"
                  count={agentsCount}
                  countLabel={agentsCount === 1 ? 'agent' : 'agents'}
                />
                <SettingsNavCard
                  to="/settings/skills"
                  icon={Sparkles}
                  title="Skills"
                  description="Reusable instruction modules agents load on demand"
                  count={skillsCount}
                  countLabel={skillsCount === 1 ? 'skill' : 'skills'}
                />
                <SettingsNavCard
                  to="/settings/mcp"
                  icon={Plug}
                  title="MCP servers"
                  description="External tool providers via Model Context Protocol"
                  count={mcpCount}
                  countLabel={mcpCount === 1 ? 'server' : 'servers'}
                />
                <SettingsNavCard
                  to="/settings/providers"
                  icon={KeyRound}
                  title="Providers"
                  description="Configure API keys and OAuth model providers"
                  count={connectedProvidersCount}
                  countLabel="connected"
                />
              </div>
            </section>

            <section>
              <SectionHeader>System</SectionHeader>
              <div className="space-y-2">
                <SettingsNavCard
                  to="/settings/sandbox"
                  icon={Shield}
                  title="Sandbox"
                  description="Files and folders agents cannot access"
                  count={sandboxCount}
                  countLabel={sandboxCount === 1 ? 'pattern' : 'patterns'}
                />
                <SettingsNavCard
                  to="/settings/multimodal"
                  icon={Image}
                  title="Multimodal"
                  description="Configure image and video generation defaults"
                  count={null}
                  countLabel=""
                />
                <SettingsNavCard
                  to="/settings/dream"
                  icon={Moon}
                  title="Dream"
                  description="Cron agent that synthesises sessions into wiki topics"
                  count={null}
                  countLabel=""
                />
                <SettingsNavCard
                  to="/settings/notifications"
                  icon={Bell}
                  title="Notifications"
                  description="Control desktop notifications and send a test notification"
                  count={null}
                  countLabel=""
                />
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  )
}
