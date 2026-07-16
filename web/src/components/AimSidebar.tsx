/**
 * AimSidebar — AIM mode's navigation: mode switch (Forge|Coding|AIM),
 * the list of AIM projects, and each project's feature items rendered as
 * an expandable dropdown (aim-mode-shell-ux-spec.md v2.2 §3.1).
 *
 * Shares the shell chrome of the other two sidebars (spec §7 / R8): the
 * same resizable width + collapse-to-icon-rail mechanics as Sidebar and
 * CodingSidebar, the same floating-card styling, and the same footer trio
 * (Settings · health · theme). It stays much smaller than CodingSidebar:
 * AIM projects have a fixed set of five features, no free-form workspace
 * tree, and — deliberately — no per-day session list (per-run sessions are
 * numerous and auto-archived; runs live in each project's Pipelines/Runs
 * screens instead). A single polled query lights a running dot on projects
 * with an active pipeline run.
 */

import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import {
  BookMarked,
  BookOpen,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  LayoutDashboard,
  Plus,
  Settings,
  Workflow,
} from 'lucide-react'
import { ModeSwitchTabs, ModeSwitchRail } from '@/components/ModeSwitchTabs'
import { ThemeToggle } from '@/components/ThemeToggle'
import { HealthDot } from '@/components/HealthDot'
import { listTeamSessions } from '@/api/client'
import { useAimProjectsQuery } from '@/queries/useAimProjectsQuery'
import { queryKeys } from '@/queries/keys'
import { usePlatform } from '@/hooks/use-platform'
import { useResizableWidth } from '@/hooks/use-resizable-width'
import { useUIStore } from '@/stores/useUIStore'
import { cn } from '@/lib/utils'
import type { LucideIcon } from 'lucide-react'

export type AimFeature = 'overview' | 'kb' | 'rulebook' | 'pipelines' | 'runs'

export const AIM_FEATURES: { key: AimFeature; label: string; Icon: LucideIcon }[] = [
  { key: 'overview', label: 'Overview', Icon: LayoutDashboard },
  { key: 'kb', label: 'Knowledge Base', Icon: BookOpen },
  { key: 'rulebook', label: 'Rulebook', Icon: BookMarked },
  { key: 'pipelines', label: 'Pipelines', Icon: Workflow },
  { key: 'runs', label: 'Runs & Reports', Icon: ClipboardList },
]

const LAST_AIM_PROJECT_KEY = 'oa-last-aim-project'

export function saveLastAimProject(projectId: string): void {
  try {
    localStorage.setItem(LAST_AIM_PROJECT_KEY, projectId)
  } catch {
    // ignore storage failures
  }
}

export function loadLastAimProject(): string | null {
  try {
    return localStorage.getItem(LAST_AIM_PROJECT_KEY)
  } catch {
    return null
  }
}

interface AimSidebarProps {
  activeProjectId?: string
  activeFeature?: AimFeature
  onNewProject: () => void
  /** Desktop icon-rail state — owned by the AIM layout so its toggle
   * button (between sidebar and content) can flip it, like coding. */
  collapsed: boolean
}

export function AimSidebar({
  activeProjectId,
  activeFeature,
  onNewProject,
  collapsed,
}: AimSidebarProps) {
  const navigate = useNavigate()
  const { isMacOverlay } = usePlatform()
  const projectsQuery = useAimProjectsQuery()
  const projects = projectsQuery.data ?? []
  // The active project is always expanded; others remember their toggle.
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(activeProjectId ? [activeProjectId] : []),
  )

  const resizable = useResizableWidth({
    storageKey: 'oa.aimSidebar.width',
    defaultWidth: 240,
    minWidth: 200,
    maxWidth: 400,
    edge: 'right',
    disabled: collapsed,
  })

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
      return next
    })
  }

  const desktopWidth = collapsed ? (isMacOverlay ? 70 : 56) : resizable.width

  // Collapsed: icon rail, mirroring the other two sidebars' collapsed strips.
  if (collapsed) {
    return (
      <div
        className="relative flex h-full shrink-0 flex-col items-center gap-1 overflow-hidden p-1 transition-[width] duration-200"
        style={{ width: desktopWidth, minWidth: desktopWidth }}
      >
        <div
          className={`flex w-full shrink-0 flex-col items-center gap-0.5 rounded-[10px] bg-(--bg-sidebar)/80 px-1 pb-2 shadow-sm backdrop-blur-xl ${isMacOverlay ? 'pt-10' : 'pt-2'}`}
        >
          <ModeSwitchRail active="aim" />
          <button
            type="button"
            onClick={onNewProject}
            title="New / Join project"
            className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
          >
            <Plus size={15} aria-hidden="true" />
          </button>
        </div>
        <div className="flex-1" />
        <div className="flex w-full shrink-0 flex-col items-center gap-1 rounded-[10px] bg-(--bg-sidebar)/80 px-1 py-2 shadow-sm backdrop-blur-xl">
          <button
            type="button"
            onClick={() => useUIStore.getState().openSettings()}
            className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Settings"
            title="Settings"
          >
            <Settings size={14} aria-hidden="true" />
          </button>
          <ThemeToggle collapsed />
          <HealthDot />
        </div>
      </div>
    )
  }

  return (
    <div
      className="relative flex h-full shrink-0 flex-col overflow-hidden p-1 transition-[width] duration-200"
      style={{ width: desktopWidth, minWidth: desktopWidth }}
    >
      {/* Resize handle — same affordance as the other two sidebars. */}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize AIM sidebar"
        title="Drag to resize · double-click to reset"
        className="absolute right-0 top-0 z-20 h-full w-1 cursor-col-resize transition-colors hover:bg-(--color-accent)/40"
        onPointerDown={resizable.startResize}
        onDoubleClick={resizable.resetWidth}
      />

      <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-[10px] bg-(--bg-sidebar)/80 shadow-sm backdrop-blur-xl">
        {/* Mode switch — shared tab strip, same as forge/coding sidebars */}
        <div className={`shrink-0 px-2 ${isMacOverlay ? 'pt-10' : 'pt-2'}`}>
          <ModeSwitchTabs active="aim" />
        </div>

        {/* Project list */}
        <nav aria-label="AIM projects" className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
          <div className="flex items-center justify-between px-1 pb-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-muted)">
              Projects
            </span>
            <button
              type="button"
              onClick={onNewProject}
              className="flex h-4 w-4 items-center justify-center rounded text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text)"
              title="New / Join migration project"
              aria-label="New / Join migration project"
            >
              <Plus size={10} aria-hidden="true" />
            </button>
          </div>
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
                        } else {
                          toggleProject(project.id)
                        }
                      }}
                      className={cn(
                        'flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-xs transition-colors',
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
                      <span className="min-w-0 flex-1 truncate">{project.name}</span>
                      {hasRunning && (
                        <span
                          className="h-1.5 w-1.5 shrink-0 rounded-full bg-(--color-accent)"
                          aria-label="Project has a running pipeline"
                          title="A pipeline is running in this project"
                        />
                      )}
                    </button>
                    {isExpanded && (
                      <div className="ml-3 space-y-0.5 border-l border-(--color-border) pl-2 pt-0.5">
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
                            }}
                            className={cn(
                              'flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-xs transition-colors',
                              isActive && activeFeature === key
                                ? 'bg-(--bg-key) text-(--color-accent)'
                                : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
                            )}
                          >
                            <Icon size={12} className="shrink-0" aria-hidden="true" />
                            <span className="truncate">{label}</span>
                            {key === 'pipelines' && hasRunning && (
                              <span className="ml-auto h-1.5 w-1.5 shrink-0 rounded-full bg-(--color-accent)" />
                            )}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </nav>

        {/* Footer trio — mirrors the forge/coding sidebars so all three
            modes feel like the same shell. */}
        <div className="flex shrink-0 items-center justify-between gap-2 border-t border-(--color-border) px-3 py-2 pb-safe">
          <button
            type="button"
            onClick={() => useUIStore.getState().openSettings()}
            className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Settings"
            title="Settings"
          >
            <Settings size={14} aria-hidden="true" />
          </button>
          <div className="flex items-center gap-2">
            <HealthDot />
            <ThemeToggle collapsed />
          </div>
        </div>
      </div>
    </div>
  )
}
