/**
 * SettingsSidebar — the persistent navigation rail for the settings screen.
 *
 * Items are grouped by what the user is actually configuring (models, the
 * agent team, machine-level behavior, then the app itself) so the list reads
 * as four short scans instead of one long one.
 */
import { useLocation } from '@tanstack/react-router'
import { motion } from 'framer-motion'
import {
  ArrowLeft,
  BarChart3,
  Bell,
  Info,
  KeyRound,
  Moon,
  Palette,
  Plug,
  Search,
  Server,
  Shield,
  Sparkles,
  Stethoscope,
  Wrench,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useMemo, useState } from 'react'

import { cn } from '@/lib/utils'
import { useMotionPreset } from '@/lib/motion'
import { usePlatform } from '@/hooks/use-platform'
import { useTauriDrag } from '@/hooks/use-tauri-drag'
import {
  useAgentFilesQuery,
  useMcpServersQuery,
  useSandboxSettingsQuery,
  useSkillFilesQuery,
} from '@/queries'
import { useUIStore } from '@/stores/useUIStore'
import { Skeleton } from '@/components/ui/skeleton'

type SidebarPath =
  | '/settings/providers'
  | '/settings/connection'
  | '/settings/agents'
  | '/settings/skills'
  | '/settings/mcp'
  | '/settings/sandbox'
  | '/settings/dream'
  | '/settings/notifications'
  | '/settings/appearance'
  | '/settings/diagnostics'
  | '/settings/telemetry'
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

interface SidebarSection {
  label: string
  items: SidebarItem[]
}

function SidebarRow({
  item,
  active,
  onNavigate,
}: {
  item: SidebarItem
  active: boolean
  onNavigate?: (path: string) => void
}) {
  const Icon = item.icon
  const preset = useMotionPreset()

  const go = () => {
    if (onNavigate) {
      onNavigate(item.to)
      return
    }
    useUIStore.getState().navigateSettings(item.to.replace(/^\/settings\/?/, ''))
  }

  return (
    <button
      type="button"
      onClick={go}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'group relative mx-2 flex min-h-11 items-center gap-2.5 rounded-lg px-3 text-left text-sm transition-[background-color,color,transform] duration-200 active:scale-[0.985]',
        'text-(--color-text-2) hover:bg-(--bg-key)/70 hover:text-(--color-text)',
        'focus-visible:ring-3 focus-visible:ring-(--focus-ring)/40 focus-visible:outline-none',
        active && 'text-(--color-text)',
      )}
    >
      {/* One indicator instance slides between rows, which makes the section
          change legible instead of blinking on and off. */}
      {active && (
        <motion.span
          layoutId="settings-nav-active"
          transition={preset.spring}
          className="absolute inset-0 -z-10 rounded-md bg-(--bg-key)"
          aria-hidden="true"
        />
      )}
      <Icon
        size={15}
        className={cn('shrink-0', active ? 'text-(--color-text)' : 'text-(--color-text-muted)')}
        aria-hidden="true"
      />
      <span className={cn('min-w-0 flex-1 truncate', active && 'font-semibold')}>{item.label}</span>
      {item.count === null ? (
        <Skeleton className="h-3 w-5 shrink-0 rounded" />
      ) : item.count !== undefined ? (
        <span className="shrink-0 font-mono text-xs tabular-nums text-(--color-text-muted)">
          {item.count}
        </span>
      ) : null}
    </button>
  )
}

interface SettingsSidebarProps {
  /** Override the active path for the store-driven settings screen. */
  currentPath?: string
  /** When provided, row clicks call this instead of navigating via the store. */
  onNavigate?: (path: string) => void
  /** Return to the app surface that opened Settings. */
  onBack?: () => void
}

export function SettingsSidebar({ currentPath, onNavigate, onBack }: SettingsSidebarProps = {}) {
  const { pathname: routePathname } = useLocation()
  const pathname = currentPath ?? routePathname
  const [query, setQuery] = useState('')
  const { isMacOverlay } = usePlatform()
  const dragHandlers = useTauriDrag()
  const agentsQ = useAgentFilesQuery()
  const skillsQ = useSkillFilesQuery()
  const mcpQ = useMcpServersQuery()
  const sandboxQ = useSandboxSettingsQuery()

  const sections = useMemo<SidebarSection[]>(
    () => [
      {
        label: 'Models',
        items: [
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
        ],
      },
      {
        label: 'Team',
        items: [
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
        ],
      },
      {
        label: 'Machine',
        items: [
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
      },
      {
        label: 'Application',
        items: [
          {
            to: '/settings/appearance',
            label: 'Appearance',
            icon: Palette,
            matchPrefix: '/settings/appearance',
          },
          {
            to: '/settings/telemetry',
            label: 'Telemetry',
            icon: BarChart3,
            matchPrefix: '/settings/telemetry',
          },
          {
            to: '/settings/diagnostics',
            label: 'Diagnostics',
            icon: Stethoscope,
            matchPrefix: '/settings/diagnostics',
          },
          {
            to: '/settings',
            label: 'About EvoFlux',
            icon: Info,
            matchPrefix: '/settings',
          },
        ],
      },
    ],
    [
      agentsQ.data?.agents.length,
      skillsQ.data?.skills.length,
      mcpQ.data?.servers.length,
      sandboxQ.data?.denied_patterns.length,
    ],
  )

  const isActive = (matchPrefix: string): boolean => {
    if (matchPrefix === '/settings') {
      // Only highlight About on exact /settings, not on any /settings/*.
      return pathname === '/settings'
    }
    return pathname === matchPrefix || pathname.startsWith(`${matchPrefix}/`)
  }

  const normalizedQuery = query.trim().toLocaleLowerCase()
  const visibleSections = normalizedQuery
    ? sections
        .map((section) => ({
          ...section,
          items: section.items.filter((item) =>
            `${section.label} ${item.label}`.toLocaleLowerCase().includes(normalizedQuery),
          ),
        }))
        .filter((section) => section.items.length > 0)
    : sections

  const handleNavigate = (path: string) => {
    setQuery('')
    onNavigate?.(path)
  }

  return (
    <aside
      className="flex h-full w-[17rem] shrink-0 flex-col border-r border-(--color-border) bg-(--bg-sidebar)"
    >
      <div
        {...dragHandlers}
        className={cn('shrink-0 px-3 pb-3 pt-3', isMacOverlay && 'pt-11')}
      >
        {onBack && (
          <button
            type="button"
            onClick={onBack}
            className="mb-3 flex h-9 items-center gap-2 rounded-md px-2 text-sm text-(--color-text-muted) transition-[background-color,color,transform] hover:bg-(--bg-key) hover:text-(--color-text) active:scale-[0.985] focus-visible:ring-3 focus-visible:ring-(--focus-ring)/40 focus-visible:outline-none"
          >
            <ArrowLeft size={15} aria-hidden="true" />
            <span>Back to app</span>
          </button>
        )}
        <div role="search" className="relative">
          <Search
            size={14}
            aria-hidden="true"
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-(--color-text-subtle)"
          />
          <input
            type="search"
            aria-label="Search settings"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search settings..."
            className="h-9 w-full rounded-lg border border-(--color-border) bg-(--bg-input) pl-9 pr-8 text-sm text-(--color-text) outline-none transition-[border-color,box-shadow] placeholder:text-(--color-text-subtle) focus:border-(--color-accent)/55 focus:ring-3 focus:ring-(--focus-ring)/25"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              aria-label="Clear settings search"
              className="absolute right-1.5 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center rounded text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text)"
            >
              <X size={12} aria-hidden="true" />
            </button>
          )}
        </div>
      </div>

      <nav
        aria-label="Settings categories"
        className="min-h-0 flex-1 space-y-4 overflow-y-auto px-1 pb-5 pt-1"
      >
        {visibleSections.map((section) => (
          <div key={section.label} className="flex flex-col">
            <p className="px-4 pb-1.5 text-[11px] font-medium tracking-wide text-(--color-text-subtle) uppercase">
              {section.label}
            </p>
            {section.items.map((item) => (
              <SidebarRow
                key={item.to}
                item={item}
                active={isActive(item.matchPrefix)}
                onNavigate={onNavigate ? handleNavigate : undefined}
              />
            ))}
          </div>
        ))}
        {visibleSections.length === 0 && (
          <div className="px-4 py-8 text-center">
            <p className="text-sm text-(--color-text-muted)">No settings found</p>
            <button
              type="button"
              onClick={() => setQuery('')}
              className="mt-2 text-xs font-medium text-(--color-accent) hover:underline"
            >
              Clear search
            </button>
          </div>
        )}
      </nav>
    </aside>
  )
}
