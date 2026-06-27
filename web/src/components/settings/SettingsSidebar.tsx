/**
 * SettingsSidebar — wide labeled sidebar (240px) for the settings modal.
 *
 * Supports two modes:
 *   - Route-driven (default): uses TanStack Router Link + useLocation
 *   - Store-driven: uses useUIStore.navigateSettings for modal popup mode
 */
import { useLocation } from '@tanstack/react-router'
import {
  BarChart3,
  Bell,
  Info,
  KeyRound,
  Moon,
  Plug,
  Server,
  Shield,
  Sparkles,
  Wrench,
  type LucideIcon,
} from 'lucide-react'
import { useMemo } from 'react'

import { cn } from '@/lib/utils'
import {
  useAgentFilesQuery,
  useMcpServersQuery,
  useSandboxSettingsQuery,
  useSkillFilesQuery,
} from '@/queries'
import { useUIStore } from '@/stores/useUIStore'

type SidebarPath =
  | '/settings/agents'
  | '/settings/skills'
  | '/settings/mcp'
  | '/settings/providers'
  | '/settings/sandbox'
  | '/settings/connection'
  | '/settings/dream'
  | '/settings/notifications'
  | '/telemetry'
  | '/settings'

interface SidebarItem {
  to: SidebarPath
  label: string
  icon: LucideIcon
  /** Match any pathname that starts with this prefix so editor routes
   *  (e.g. /settings/agents/lead) keep the parent row active. */
  matchPrefix: string
  /** Optional badge with a live count. */
  count?: number | null
}

function GroupLabel({ children }: { children: string }) {
  return (
    <p className="px-3 pt-4 pb-1.5 font-mono text-xs font-semibold tracking-wider text-(--color-text-muted) uppercase">
      {children}
    </p>
  )
}

function SidebarRow({ item, active, onNavigate }: { item: SidebarItem; active: boolean; onNavigate?: (path: string) => void }) {
  const Icon = item.icon
  if (onNavigate) {
    return (
      <button
        type="button"
        onClick={() => onNavigate(item.to)}
        aria-current={active ? 'page' : undefined}
        className={cn(
          'group relative mx-2 flex h-9 items-center gap-2.5 rounded-md px-3 text-left text-sm transition-colors',
          'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)',
          'focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-(--focus-ring)/40',
          active && 'bg-(--bg-key) font-semibold text-(--color-text)',
        )}
      >
        <Icon
          size={15}
          className={cn(
            'shrink-0',
            active ? 'text-(--color-text)' : 'text-(--color-text-muted)',
          )}
          aria-hidden="true"
        />
        <span className="min-w-0 flex-1 truncate">{item.label}</span>
        {item.count !== undefined && item.count !== null && (
          <span
            className={cn(
              'shrink-0 font-mono text-xs tabular-nums',
              active ? 'font-semibold text-(--color-text-muted)' : 'text-(--color-text-muted)',
            )}
          >
            {item.count}
          </span>
        )}
      </button>
    )
  }
  return (
    <button
      type="button"
      onClick={() => useUIStore.getState().navigateSettings(item.to.replace(/^\/settings\/?/, ''))}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'group relative mx-2 flex h-9 items-center gap-2.5 rounded-md px-3 text-left text-sm transition-colors',
        'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)',
        'focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-(--focus-ring)/40',
        active && 'bg-(--bg-key) font-semibold text-(--color-text)',
      )}
    >
      <Icon
        size={15}
        className={cn(
          'shrink-0',
          active ? 'text-(--color-text)' : 'text-(--color-text-muted)',
        )}
        aria-hidden="true"
      />
      <span className="min-w-0 flex-1 truncate">{item.label}</span>
      {item.count !== undefined && item.count !== null && (
        <span
          className={cn(
            'shrink-0 font-mono text-xs tabular-nums',
            active ? 'font-semibold text-(--color-text-muted)' : 'text-(--color-text-muted)',
          )}
        >
          {item.count}
        </span>
      )}
    </button>
  )
}

interface SettingsSidebarProps {
  /** Override the active path (for store-driven modal mode). */
  currentPath?: string
  /** When provided, row clicks call this instead of navigating via Link. */
  onNavigate?: (path: string) => void
}

export function SettingsSidebar({ currentPath, onNavigate }: SettingsSidebarProps = {}) {
  const { pathname: routePathname } = useLocation()
  const pathname = currentPath ?? routePathname
  const agentsQ = useAgentFilesQuery()
  const skillsQ = useSkillFilesQuery()
  const mcpQ = useMcpServersQuery()
  const sandboxQ = useSandboxSettingsQuery()

  const configurationItems = useMemo<SidebarItem[]>(
    () => [
      {
        to: '/settings/agents',
        label: 'Agents',
        icon: Wrench,
        matchPrefix: '/settings/agents',
        count: agentsQ.data?.agents.length ?? null,
      },
      {
        to: '/settings/skills',
        label: 'Skills',
        icon: Sparkles,
        matchPrefix: '/settings/skills',
        count: skillsQ.data?.skills.length ?? null,
      },
      {
        to: '/settings/mcp',
        label: 'MCP servers',
        icon: Plug,
        matchPrefix: '/settings/mcp',
        count: mcpQ.data?.servers.length ?? null,
      },
      {
        to: '/settings/providers',
        label: 'Providers',
        icon: KeyRound,
        matchPrefix: '/settings/providers',
      },
      {
        to: '/settings/connection',
        label: 'Connection',
        icon: Server,
        matchPrefix: '/settings/connection',
      },
      {
        to: '/settings/sandbox',
        label: 'Sandbox',
        icon: Shield,
        matchPrefix: '/settings/sandbox',
        count: sandboxQ.data?.denied_patterns.length ?? null,
      },
      {
        to: '/settings/dream',
        label: 'Dream',
        icon: Moon,
        matchPrefix: '/settings/dream',
      },
      {
        to: '/settings/notifications',
        label: 'Notifications',
        icon: Bell,
        matchPrefix: '/settings/notifications',
      },
    ],
    [
      agentsQ.data?.agents.length,
      skillsQ.data?.skills.length,
      mcpQ.data?.servers.length,
      sandboxQ.data?.denied_patterns.length,
    ],
  )

  const aboutItems = useMemo<SidebarItem[]>(
    () => [
      {
        to: '/telemetry',
        label: 'Telemetry',
        icon: BarChart3,
        matchPrefix: '/telemetry',
      },
      {
        to: '/settings',
        label: 'About EvoFlux',
        icon: Info,
        matchPrefix: '/settings',
      },
    ],
    [],
  )

  const isActive = (matchPrefix: string): boolean => {
    if (matchPrefix === '/settings') {
      // Only highlight About on exact /settings, not on any /settings/*.
      return pathname === '/settings'
    }
    return (
      pathname === matchPrefix || pathname.startsWith(`${matchPrefix}/`)
    )
  }

  return (
    <nav
      aria-label="Settings categories"
      className="flex h-full w-[min(18rem,calc(100vw-2rem))] shrink-0 flex-col overflow-y-auto rounded-[10px] bg-(--bg-sidebar)/80 shadow-sm backdrop-blur-xl md:w-60"
    >
      <GroupLabel>Configuration</GroupLabel>
      <div className="flex flex-col">
        {configurationItems.map((item) => (
          <SidebarRow key={item.to} item={item} active={isActive(item.matchPrefix)} onNavigate={onNavigate} />
        ))}
      </div>

      <div className="mx-3 my-3 h-px bg-(--color-border)" role="separator" aria-hidden="true" />

      <GroupLabel>About</GroupLabel>
      <div className="flex flex-col">
        {aboutItems.map((item) => (
          <SidebarRow key={item.to} item={item} active={isActive(item.matchPrefix)} onNavigate={onNavigate} />
        ))}
      </div>
    </nav>
  )
}
