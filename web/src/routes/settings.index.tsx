/**
 * /settings — "About EvoFlux" landing.
 *
 * Desktop hides the category list (the sidebar rail already shows it);
 * mobile re-uses this page as the settings hub by rendering nav rows in the
 * same four groups as the sidebar.
 */
import {
  BarChart3,
  Bell,
  Bot,
  BrainCircuit,
  ChevronRight,
  Server,
  Info,
  KeyRound,
  Moon,
  Palette,
  Plug,
  Shield,
  Sparkles,
  Stethoscope,
  type LucideIcon,
} from 'lucide-react'

import { cn } from '@/lib/utils'
import { useIsMobile } from '@/hooks/use-mobile'
import { useSettingsNavigate } from '@/contexts/SettingsContext'
import { SettingsGroup, SettingsPage, SettingsRow } from '@/components/settings/SettingsLayout'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useAgentFilesQuery,
  useHealthQuery,
  useMcpServersQuery,
  useProvidersQuery,
  useSandboxSettingsQuery,
  useSkillFilesQuery,
} from '@/queries'
import { useUIStore } from '@/stores/useUIStore'

interface NavRow {
  to: string
  icon: LucideIcon
  title: string
  description: string
  count?: number | null
  countLabel?: string
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
  const agentsQ = useAgentFilesQuery()
  const skillsQ = useSkillFilesQuery()
  const mcpQ = useMcpServersQuery()
  const providersQ = useProvidersQuery()
  const sandboxQ = useSandboxSettingsQuery()
  const healthQ = useHealthQuery()

  const agentsCount = agentsQ.data?.agents.length ?? null
  const skillsCount = skillsQ.data?.skills.length ?? null
  const mcpCount = mcpQ.data?.servers.length ?? null
  const connectedProviders =
    providersQ.data?.providers.filter((provider) => provider.is_configured).length ?? null
  const sandboxCount = sandboxQ.data?.denied_patterns.length ?? null
  const version = healthQ.data?.version

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
        },
        {
          to: '/settings/skills',
          icon: Sparkles,
          title: 'Skills',
          description: 'Instruction packs agents load on demand',
          count: skillsCount,
          countLabel: skillsCount === 1 ? 'skill' : 'skills',
        },
        {
          to: '/settings/mcp',
          icon: Plug,
          title: 'MCP servers',
          description: 'External tools over Model Context Protocol',
          count: mcpCount,
          countLabel: mcpCount === 1 ? 'server' : 'servers',
        },
      ],
    },
    {
      label: 'Knowledge',
      rows: [
        {
          to: '/settings/memory',
          icon: BrainCircuit,
          title: 'Memory',
          description: 'Long-term knowledge, sources and pending notes',
        },
        {
          to: '/settings/dream',
          icon: Moon,
          title: 'Dream',
          description: 'Synthesize new material into durable memory',
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
          to: '/settings/sandbox',
          icon: Shield,
          title: 'Sandbox',
          description: 'Agent filesystem, process and worktree isolation',
          count: sandboxCount,
          countLabel: sandboxCount === 1 ? 'pattern' : 'patterns',
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
          icon: BarChart3,
          title: 'Telemetry',
          description: 'Span aggregates, latency and recent traces',
        },
        {
          to: '/settings/diagnostics',
          icon: Stethoscope,
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
      <SettingsGroup title="Backend">
        <SettingsRow
          label="Backend connection"
          description="Connect to an existing EvoFlux server, or switch back to the bundled local sidecar when it is available."
          control={
            <Button
              size="sm"
              variant="outline"
              onClick={() => useUIStore.getState().navigateSettings('connection')}
            >
              Configure
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
