/**
 * /settings — "About EvoFlux" landing.
 *
 * Desktop hides the category list (the sidebar rail already shows it);
 * mobile re-uses this page as the settings hub by rendering nav rows in the
 * same four groups as the sidebar.
 */
import {
  Activity,
  Bell,
  Blocks,
  BookOpen,
  Bot,
  Brain,
  Building2,
  ChartColumn,
  ChevronRight,
  GitBranch,
  Globe2,
  Info,
  KeyRound,
  Palette,
  Plug,
  RefreshCw,
  Server,
  Shield,
  Sparkles,
  type LucideIcon,
} from 'lucide-react'

import { cn } from '@/lib/utils'
import { useIsMobile } from '@/hooks/use-mobile'
import { useSettingsNavigate } from '@/contexts/SettingsContext'
import { SettingsGroup, SettingsPage, SettingsRow } from '@/components/settings/SettingsLayout'
import { Button } from '@/components/ui/button'
import { useUIStore } from '@/stores/useUIStore'
import { Skeleton } from '@/components/ui/skeleton'
import { EnterpriseAttentionDot } from '@/components/settings/EnterpriseAttentionDot'
import {
  useAgentFilesQuery,
  useConductorStatusQuery,
  useHealthQuery,
  useMcpServersQuery,
  useProvidersQuery,
  useSandboxSettingsQuery,
  useSkillFilesQuery,
} from '@/queries'
import { useActiveSkillDiscoveryScope } from '@/hooks/useActiveSkillDiscoveryScope'
import { enterpriseAttentionCount, resourceHasUpdate } from '@/lib/enterprise'
import { usePlatform } from '@/hooks/use-platform'
import { useAppUpdaterStore } from '@/stores/useAppUpdaterStore'

interface NavRow {
  to: string
  icon: LucideIcon
  title: string
  description: string
  count?: number | null
  countLabel?: string
  attention?: string | null
}

function SettingsNavRow({ row }: { row: NavRow }) {
  const navigate = useSettingsNavigate()
  const Icon = row.icon
  return (
    <button
      type="button"
      onClick={() => navigate(row.to)}
      className={cn(
        'group flex w-full items-center gap-3 px-4 py-3.5 text-left transition-colors',
        'hover:bg-(--bg-key)/65',
        'focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-(--focus-ring)/40 focus-visible:outline-none',
      )}
    >
      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-(--bg-key) text-(--color-text-muted) transition-colors group-hover:bg-(--color-accent-soft) group-hover:text-(--color-accent)">
        <Icon size={16} aria-hidden="true" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-(--color-text)">{row.title}</span>
          {row.attention ? (
            <EnterpriseAttentionDot label={row.attention} />
          ) : null}
          {row.count === null ? (
            <Skeleton className="h-3 w-12 rounded" />
          ) : row.count !== undefined ? (
            <span className="rounded-full bg-(--bg-key) px-2 py-0.5 font-mono text-[10px] tabular-nums text-(--color-text-muted)">
              {row.count} {row.countLabel}
            </span>
          ) : null}
        </span>
        <span className="mt-0.5 block truncate text-xs text-(--color-text-muted)">
          {row.description}
        </span>
      </span>
      <ChevronRight
        size={15}
        className="shrink-0 text-(--color-text-subtle) transition-transform group-hover:translate-x-0.5"
        aria-hidden="true"
      />
    </button>
  )
}

export function SettingsHubPage() {
  const isMobile = useIsMobile()
  const platform = usePlatform()
  const navigate = useSettingsNavigate()
  const checkingForUpdate = useAppUpdaterStore((state) => state.checking)
  const checkForUpdates = useAppUpdaterStore((state) => state.check)
  const agentsQ = useAgentFilesQuery()
  const skillScope = useActiveSkillDiscoveryScope()
  const skillsQ = useSkillFilesQuery(skillScope)
  const mcpQ = useMcpServersQuery()
  const providersQ = useProvidersQuery()
  const sandboxQ = useSandboxSettingsQuery()
  const healthQ = useHealthQuery()
  const conductorQ = useConductorStatusQuery()

  const agentsCount = agentsQ.data?.agents.length ?? null
  const skillsCount = skillsQ.data?.skills.length ?? null
  const mcpCount = mcpQ.data?.servers.length ?? null
  const connectedProviders =
    providersQ.data?.providers.filter((provider) => provider.is_configured).length ?? null
  const sandboxCount = sandboxQ.data?.denied_patterns.length ?? null
  const version = healthQ.data?.version
  const enterpriseProject =
    conductorQ.data?.project_display_name ?? conductorQ.data?.project_name
  const enterpriseNotifications = enterpriseAttentionCount(conductorQ.data)
  const resourceUpdates = conductorQ.data?.resources.filter(resourceHasUpdate) ?? []
  const agentUpdateCount = resourceUpdates.filter((resource) => resource.kind === 'agent').length
  const skillUpdateCount = resourceUpdates.filter((resource) => resource.kind === 'skill').length
  const desktopUpdaterAvailable =
    platform.isTauri
    && platform.os !== 'linux'
    && platform.os !== 'ios'
    && platform.os !== 'android'
  const linuxDebInstall = platform.isTauri && platform.os === 'linux'

  const groups: Array<{ label: string; rows: NavRow[] }> = [
    {
      label: 'Intelligence',
      rows: [
        {
          to: '/settings/providers',
          icon: KeyRound,
          title: 'Providers',
          description: 'API keys and OAuth model providers',
          count: connectedProviders,
          countLabel: 'connected',
        },
        {
          to: '/settings/agents',
          icon: Bot,
          title: 'Agents',
          description: 'Model, tools and system prompt per team member',
          count: agentsCount,
          countLabel: agentsCount === 1 ? 'agent' : 'agents',
          attention: agentUpdateCount > 0
            ? `${agentUpdateCount} managed Agent ${agentUpdateCount === 1 ? 'update' : 'updates'} available`
            : null,
        },
        {
          to: '/settings/skills',
          icon: Sparkles,
          title: 'Skills',
          description: 'Instruction packs agents load on demand',
          count: skillsCount,
          countLabel: skillsCount === 1 ? 'skill' : 'skills',
          attention: skillUpdateCount > 0
            ? `${skillUpdateCount} managed Skill ${skillUpdateCount === 1 ? 'update' : 'updates'} available`
            : null,
        },
        {
          to: '/settings/mcp',
          icon: Plug,
          title: 'MCP servers',
          description: 'External tools over Model Context Protocol',
          count: mcpCount,
          countLabel: mcpCount === 1 ? 'server' : 'servers',
        },
        {
          to: '/settings/language-servers',
          icon: Blocks,
          title: 'Language servers',
          description: 'Semantic engines detected and managed per repository',
        },
      ],
    },
    {
      label: 'Knowledge',
      rows: [
        {
          to: '/settings/memory',
          icon: Brain,
          title: 'Memory',
          description: 'Long-term knowledge and Dream synthesis',
        },
      ],
    },
    {
      label: 'Workspace',
      rows: [
        {
          to: '/settings/enterprise',
          icon: Building2,
          title: 'Enterprise',
          description: enterpriseProject
            ? `Connected to ${enterpriseProject}`
            : 'Project resources, usage, updates and sync health',
          attention: enterpriseNotifications > 0
            ? `${enterpriseNotifications} Enterprise ${enterpriseNotifications === 1 ? 'notification' : 'notifications'}`
            : null,
        },
      ],
    },
    {
      label: 'System',
      rows: [
        {
          to: '/settings/connection',
          icon: Server,
          title: 'Connection',
          description: 'Point the app at a local or remote backend',
        },
        {
          to: '/settings/version-control',
          icon: GitBranch,
          title: 'Git & reviews',
          description: 'Sync, pull request reliability and safety policy',
        },
        {
          to: '/settings/sandbox',
          icon: Shield,
          title: 'Sandbox',
          description: 'Agent filesystem, process and worktree isolation',
          count: sandboxCount,
          countLabel: sandboxCount === 1 ? 'pattern' : 'patterns',
        },
        {
          to: '/settings/browser',
          icon: Globe2,
          title: 'Browser',
          description: 'Built-in WebView and WebBridge for the real browser',
        },
        {
          to: '/settings/notifications',
          icon: Bell,
          title: 'Notifications',
          description: 'Desktop alerts and test delivery',
        },
      ],
    },
    {
      label: 'Application',
      rows: [
        {
          to: '/settings/appearance',
          icon: Palette,
          title: 'Appearance',
          description: 'Theme, accent, font, scale and motion',
        },
        {
          to: '/settings/telemetry',
          icon: ChartColumn,
          title: 'Telemetry',
          description: 'Span aggregates, latency and recent traces',
        },
        {
          to: '/settings/diagnostics',
          icon: Activity,
          title: 'Diagnostics',
          description: 'Health checks across every subsystem',
        },
      ],
    },
  ]

  return (
    <SettingsPage
      icon={Info}
      title="About EvoFlux"
      lede={
        <span className="inline-flex flex-wrap items-center gap-x-1">
          <span>On-machine AI assistant, version</span>
          {version ? (
            <span>{version}.</span>
          ) : (
            <>
              <span
                aria-hidden="true"
                className="skeleton-shimmer inline-block h-3.5 w-14 rounded"
              />
              <span className="sr-only">Loading version</span>
            </>
          )}
          <span>Everything below is stored locally on this machine.</span>
        </span>
      }
    >
      <SettingsGroup title="Updates">
        <SettingsRow
          label="App updates"
          description={
            linuxDebInstall
              ? 'Linux updates are installed through a newer EvoFlux .deb package so dpkg keeps ownership consistent.'
              : desktopUpdaterAvailable
              ? 'Check GitHub Releases for a signed EvoFlux update. Downloads are verified before installation.'
              : 'Update checks are available in the packaged EvoFlux desktop app.'
          }
          control={
            <Button
              size="sm"
              variant="outline"
              disabled={!desktopUpdaterAvailable || checkingForUpdate}
              onClick={() => void checkForUpdates()}
            >
              <RefreshCw
                size={13}
                className={checkingForUpdate ? 'animate-spin' : undefined}
                aria-hidden="true"
              />
              {checkingForUpdate ? 'Checking…' : 'Check now'}
            </Button>
          }
        />
      </SettingsGroup>

      <SettingsGroup title="Backend">
        <SettingsRow
          label="Backend connection"
          description="Connect to an existing EvoFlux server, or switch back to the bundled local sidecar when it is available."
          control={
            <Button
              size="sm"
              variant="outline"
              onClick={() => navigate('connection')}
            >
              Configure
            </Button>
          }
        />
      </SettingsGroup>

      <SettingsGroup title="Help">
        <SettingsRow
          label="Guidelines"
          description="Searchable setup tips and tricks for every EvoFlux surface."
          control={
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                useUIStore.getState().closeSettings()
                useUIStore.getState().openGuidelines('getting-started')
              }}
            >
              <BookOpen size={13} aria-hidden="true" />
              Open
            </Button>
          }
        />
      </SettingsGroup>

      {/* Mobile has no sidebar rail, so this page carries the navigation. */}
      {isMobile &&
        groups.map((group) => (
          <SettingsGroup key={group.label} title={group.label}>
            {group.rows.map((row) => (
              <SettingsNavRow key={row.to} row={row} />
            ))}
          </SettingsGroup>
        ))}
    </SettingsPage>
  )
}
