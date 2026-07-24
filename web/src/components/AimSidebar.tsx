/**
 * AimSidebar — AIM mode's navigation: mode switch (Forge|Coding|AIM),
 * the list of AIM projects, and each project's feature items rendered as
 * an expandable dropdown (aim-mode-shell-ux-spec.md v2.2 §3.1).
 *
 * Shares the shell chrome of the other two sidebars (spec §7 / R8) via the
 * primitives in `@/components/shell/`: the same resizable width +
 * collapse-to-icon-rail mechanics as Sidebar and CodingSidebar, the same
 * floating-card styling, and the same footer trio (Settings · health ·
 * theme). It stays much smaller than CodingSidebar: AIM projects have a
 * fixed set of five features, no free-form workspace tree, and —
 * deliberately — no per-day session list (per-run sessions are numerous
 * and auto-archived; runs live in each project's Pipelines/Runs screens
 * instead). A single polled query lights a running dot on projects with an
 * active pipeline run.
 */

import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import {
  ChevronDown,
  ChevronRight,
  Plus,
  Search,
} from 'lucide-react'
import { ModeSwitchTabs, ModeSwitchRail } from '@/components/ModeSwitchTabs'
import {
  SidebarShell,
  SidebarCard,
  SidebarShellDivider,
  SidebarSearchTrigger,
  SidebarFooter,
} from '@/components/shell/SidebarShell'
import { CollapsibleSection } from '@/components/shell/CollapsibleSection'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import {
  AIM_FEATURES,
  saveLastAimProject,
  type AimFeature,
} from '@/lib/aim-sidebar'
import { listTeamSessions } from '@/api/client'
import { useAimProjectsQuery } from '@/queries/useAimProjectsQuery'
import { queryKeys } from '@/queries/keys'
import { usePlatform } from '@/hooks/use-platform'
import { useUIStore } from '@/stores/useUIStore'
import { cn } from '@/lib/utils'

// Runs & Reports folded into Pipelines (its run table now shows the
// aim_runs verdict inline via a Report side panel) — one less place to
// look for "what happened", since every compare/convert/test verdict
// already traces back to a pipeline run.
const AIM_EXPANDED_KEY = STORAGE_KEYS.aim.expanded

function loadAimExpanded(): string[] {
  try {
    const raw = localStorage.getItem(AIM_EXPANDED_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((id): id is string => typeof id === 'string')
  } catch {
    return []
  }
}

function saveAimExpanded(ids: string[]): void {
  try {
    localStorage.setItem(AIM_EXPANDED_KEY, JSON.stringify(ids))
  } catch {
    // ignore storage failures
  }
}

interface AimSidebarProps {
  activeProjectId?: string
  activeFeature?: AimFeature
  onNewProject: () => void
  /** Opens the command palette (search input + footer help), same as
   * the forge/coding sidebars. */
  onCommandPalette?: () => void
  mobile?: boolean
  onMobileClose?: () => void
}

export function AimSidebar({
  activeProjectId,
  activeFeature,
  onNewProject,
  onCommandPalette,
  mobile = false,
  onMobileClose,
}: AimSidebarProps) {
  const navigate = useNavigate()
  const { isMacOverlay } = usePlatform()
  // Collapse state is shared by all three mode sidebars and owned by
  // useUIStore; AppShell owns the toggle button + Ctrl+B.
  const collapsed = useUIStore((s) => s.sidebarCollapsed)
  const projectsQuery = useAimProjectsQuery()
  const projects = projectsQuery.data ?? []
  // The active project is always expanded; others remember their toggle
  // (persisted to localStorage as a plain string[] of project ids).
  const [expanded, setExpanded] = useState<Set<string>>(
    () =>
      new Set([
        ...loadAimExpanded(),
        ...(activeProjectId ? [activeProjectId] : []),
      ]),
  )

  // One poll lights the running dot for every project (mirrors coding's
  // per-project running indicator without a per-project query).
  const runningQuery = useQuery({
    queryKey: [...queryKeys.team.sessions.infinite('aim'), 'sidebar-running'],
    queryFn: () => listTeamSessions(undefined, 50, { mode: 'aim' }),
    refetchInterval: 10_000,
  })
  const runningProjects = new Set(
    (runningQuery.data?.data ?? [])
      .filter((s) => s.running && s.project_id)
      .map((s) => s.project_id as string),
  )

  const toggleProject = (projectId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(projectId)) next.delete(projectId)
      else next.add(projectId)
      saveAimExpanded([...next])
      return next
    })
  }

  // Collapsed icon rail — same two-card stack as the coding sidebar's rail.
  const rail = (
    <>
      <SidebarCard
        className={`w-full shrink-0 items-center gap-0.5 px-1 pb-2 ${isMacOverlay ? 'pt-10' : 'pt-2'}`}
      >
        <ModeSwitchRail active="aim" />
        {onCommandPalette && (
          <button
            type="button"
            onClick={onCommandPalette}
            title="Search (Ctrl+P)"
            className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
          >
            <Search size={15} aria-hidden="true" />
          </button>
        )}
        <button
          type="button"
          onClick={onNewProject}
          title="New / Join project"
          className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
        >
          <Plus size={15} aria-hidden="true" />
        </button>
      </SidebarCard>
      <div className="flex-1" />
      <SidebarCard className="w-full shrink-0">
        <SidebarFooter collapsed onCommandPalette={onCommandPalette} />
      </SidebarCard>
    </>
  )

  const content = (
    <SidebarCard className="h-full">
        {/* Mode switch — shared tab strip, same as forge/coding sidebars */}
        <div className={`shrink-0 px-2 ${isMacOverlay ? 'pt-10' : 'pt-2'}`}>
          <ModeSwitchTabs active="aim" onNavigate={onMobileClose} />
        </div>

        {/* Search trigger — opens the command palette (Ctrl+P), same
            placement + markup as the forge/coding sidebars. */}
        {onCommandPalette && (
          <div className="shrink-0 px-2 pt-2">
            <SidebarSearchTrigger
              onClick={() => {
                onCommandPalette()
                onMobileClose?.()
              }}
            />
          </div>
        )}

        {/* Project list */}
        <nav aria-label="AIM projects" className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
          <CollapsibleSection
            label="Projects"
            onAdd={() => {
              onNewProject()
              onMobileClose?.()
            }}
            addLabel="New / Join migration project"
          />
          {projectsQuery.isLoading ? (
            <p className="px-2 py-1.5 text-xs text-(--color-text-subtle)">Loading projects…</p>
          ) : projects.length === 0 ? (
            <p className="px-2 py-1.5 text-xs text-(--color-text-subtle)">
              No migration projects yet.
            </p>
          ) : (
            <div className="space-y-0.5">
              {projects.map((project) => {
                const isActive = project.id === activeProjectId
                const isExpanded = isActive || expanded.has(project.id)
                const hasRunning = runningProjects.has(project.id)
                const rulebook = (
                  project.settings?.aim as { rulebook?: { id?: string } } | undefined
                )?.rulebook
                return (
                  <div key={project.id}>
                    <button
                      type="button"
                      onClick={() => {
                        if (!isActive) {
                          saveLastAimProject(project.id)
                          navigate({
                            to: '/aim/$projectId/$feature',
                            params: { projectId: project.id, feature: 'overview' },
                          })
                          onMobileClose?.()
                        } else {
                          toggleProject(project.id)
                        }
                      }}
                      className={cn(
                        'flex w-full items-center gap-1.5 rounded-xs px-2 py-1.5 text-left text-xs transition-colors',
                        isActive
                          ? 'bg-(--bg-key) font-medium text-(--color-text)'
                          : 'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)',
                      )}
                      title={rulebook?.id ? `${project.name} · ${rulebook.id}` : project.name}
                    >
                      {isExpanded ? (
                        <ChevronDown size={12} className="shrink-0 text-(--color-text-subtle)" />
                      ) : (
                        <ChevronRight size={12} className="shrink-0 text-(--color-text-subtle)" />
                      )}
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{project.name}</span>
                        {rulebook?.id && (
                          <span className="block truncate font-mono text-[10px] font-normal text-(--color-text-subtle)">
                            {rulebook.id}
                          </span>
                        )}
                      </span>
                      {hasRunning && (
                        <span
                          className="h-1.5 w-1.5 shrink-0 rounded-full bg-(--color-accent)"
                          aria-label="Project has a running pipeline"
                          title="A pipeline is running in this project"
                        />
                      )}
                    </button>
                    <AnimatePresence initial={false}>
                      {isExpanded && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          className="overflow-hidden"
                        >
                          {/* Feature rows read as children: quieter than the
                              project row, hung off an indent guide aligned
                              under the chevron — same text-xs/rounded-md/px-2
                              sizing as Coding's nested repo/session rows. */}
                          <div className="mb-1 ml-[13px] space-y-px border-l border-(--color-border) pl-1.5 pt-0.5">
                            {AIM_FEATURES.map(({ key, label, Icon }) => (
                              <button
                                key={key}
                                type="button"
                                onClick={() => {
                                  saveLastAimProject(project.id)
                                  navigate({
                                    to: '/aim/$projectId/$feature',
                                    params: { projectId: project.id, feature: key },
                                  })
                                  onMobileClose?.()
                                }}
                                className={cn(
                                  'flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-xs transition-colors',
                                  isActive && activeFeature === key
                                    ? 'bg-(--bg-key) font-medium text-(--color-accent)'
                                    : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
                                )}
                              >
                                <Icon size={11} className="shrink-0" aria-hidden="true" />
                                <span className="truncate">{label}</span>
                                {key === 'pipelines' && hasRunning && (
                                  <span className="ml-auto h-1.5 w-1.5 shrink-0 rounded-full bg-(--color-accent)" />
                                )}
                              </button>
                            ))}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                )
              })}
            </div>
          )}
        </nav>

        {/* Footer trio — mirrors the forge/coding sidebars so all three
            modes feel like the same shell. */}
        <SidebarShellDivider />
        <SidebarFooter onCommandPalette={onCommandPalette} onAction={onMobileClose} />
      </SidebarCard>
  )

  if (mobile) {
    return <div className="h-full w-full overflow-hidden p-1">{content}</div>
  }

  return (
    <SidebarShell
      collapsed={collapsed}
      rail={rail}
      resizeLabel="Resize AIM sidebar"
    >
      {content}
    </SidebarShell>
  )
}
