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
import {
  Activity,
  ChevronRight,
  FolderKanban,
  Plus,
  Search,
  Trash2,
} from 'lucide-react'
import { ModeSwitchTabs, ModeSwitchRail } from '@/components/ModeSwitchTabs'
import {
  SidebarShell,
  SidebarCard,
  SidebarShellDivider,
  SidebarSearchTrigger,
  SidebarFooter,
} from '@/components/shell/SidebarShell'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  AIM_FEATURES,
  clearLastAimProject,
  saveLastAimProject,
  type AimFeature,
} from '@/lib/aim-sidebar'
import { listTeamSessions } from '@/api/client'
import {
  useAimProjectsQuery,
  useRemoveAimProjectMutation,
} from '@/queries/useAimProjectsQuery'
import { queryKeys } from '@/queries/keys'
import { usePlatform } from '@/hooks/use-platform'
import { useToastStore } from '@/stores/useToastStore'
import { useUIStore } from '@/stores/useUIStore'
import { cn } from '@/lib/utils'
import type { CodingProject } from '@/api/types'

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
  const removeProjectMutation = useRemoveAimProjectMutation()
  const [removeProjectTarget, setRemoveProjectTarget] =
    useState<CodingProject | null>(null)
  const projects = projectsQuery.data ?? []
  const activeProject = projects.find((project) => project.id === activeProjectId)

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

        <nav aria-label="AIM navigation" className="min-h-0 flex-1 overflow-y-auto px-2 pb-3 pt-3">
          {projectsQuery.isLoading ? (
            <AimProjectListSkeleton />
          ) : projects.length === 0 ? (
            <div className="px-1">
              <div className="flex items-center justify-between pb-2">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-muted)">
                  Migration projects
                </span>
                <button
                  type="button"
                  onClick={() => {
                    onNewProject()
                    onMobileClose?.()
                  }}
                  className="flex h-7 w-7 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                  aria-label="New or join migration project"
                  title="New or join migration project"
                >
                  <Plus size={14} aria-hidden="true" />
                </button>
              </div>
              <div className="border-y border-(--color-border) py-6 text-center">
                <FolderKanban size={18} className="mx-auto mb-2 text-(--color-text-subtle)" aria-hidden="true" />
                <p className="text-xs font-medium text-(--color-text-2)">No migration projects</p>
              </div>
            </div>
          ) : (
            <div>
              {activeProject && (
                <section aria-labelledby="current-migration-label" className="px-1">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span id="current-migration-label" className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-muted)">
                      Current migration
                    </span>
                    {runningProjects.has(activeProject.id) && (
                      <span className="flex items-center gap-1 rounded-full bg-(--color-accent)/10 px-1.5 py-0.5 text-[9px] font-semibold text-(--color-accent)">
                        <Activity size={9} aria-hidden="true" />
                        Running
                      </span>
                    )}
                  </div>
                  <div className="flex min-w-0 items-center gap-2.5 pb-2.5">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-(--bg-key) text-(--color-accent) ring-1 ring-(--color-border)">
                      <FolderKanban size={15} aria-hidden="true" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold text-(--color-text)">
                        {activeProject.name}
                      </span>
                      <span className="block truncate font-mono text-[9px] text-(--color-text-subtle)">
                        {getRulebookId(activeProject) ?? 'No rulebook linked'}
                      </span>
                    </span>
                    <button
                      type="button"
                      onClick={() => setRemoveProjectTarget(activeProject)}
                      disabled={removeProjectMutation.isPending}
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-(--color-text-subtle) transition-colors hover:bg-(--color-error-subtle) hover:text-(--color-error) disabled:cursor-not-allowed disabled:opacity-40"
                      aria-label={`Remove project ${activeProject.name} from AIM`}
                      title={`Remove ${activeProject.name} from AIM`}
                    >
                      <Trash2 size={13} aria-hidden="true" />
                    </button>
                  </div>
                  <div className="grid grid-cols-2 gap-1" aria-label={`${activeProject.name} sections`}>
                    {AIM_FEATURES.map(({ key, label, Icon }) => {
                      const isFeatureActive = activeFeature === key
                      return (
                        <button
                          key={key}
                          type="button"
                          onClick={() => {
                            saveLastAimProject(activeProject.id)
                            navigate({
                              to: '/aim/$projectId/$feature',
                              params: { projectId: activeProject.id, feature: key },
                            })
                            onMobileClose?.()
                          }}
                          className={cn(
                            'flex h-9 min-w-0 items-center gap-2 rounded-md px-2 text-left text-[11px] font-medium transition-colors',
                            isFeatureActive
                              ? 'bg-(--bg-key) text-(--color-text) shadow-sm ring-1 ring-(--color-border-strong)'
                              : 'bg-(--bg-key)/60 text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
                          )}
                          aria-current={isFeatureActive ? 'page' : undefined}
                        >
                          <Icon
                            size={13}
                            className={cn('shrink-0', isFeatureActive && 'text-(--color-accent)')}
                            aria-hidden="true"
                          />
                          <span className="min-w-0 truncate">{label}</span>
                          {key === 'pipelines' && runningProjects.has(activeProject.id) && !isFeatureActive && (
                            <span className="ml-auto h-1.5 w-1.5 shrink-0 rounded-full bg-(--color-accent)" aria-label="Pipeline running" />
                          )}
                        </button>
                      )
                    })}
                  </div>
                </section>
              )}

              <section aria-labelledby="project-switcher-label" className={cn('px-1', activeProject && 'mt-4 border-t border-(--color-border) pt-3')}>
                <div className="mb-1.5 flex items-center justify-between gap-2">
                  <span id="project-switcher-label" className="flex min-w-0 items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-(--color-text-muted)">
                    {activeProject ? 'Switch project' : 'Migration projects'}
                    <span className="rounded-full bg-(--bg-key) px-1.5 py-px text-[9px] font-semibold tracking-normal text-(--color-text-subtle)">
                      {projects.length}
                    </span>
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      onNewProject()
                      onMobileClose?.()
                    }}
                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                    aria-label="New or join migration project"
                    title="New or join migration project"
                  >
                    <Plus size={14} aria-hidden="true" />
                  </button>
                </div>
                <div className="space-y-0.5">
                  {projects
                    .filter((project) => project.id !== activeProject?.id)
                    .map((project) => {
                      const hasRunning = runningProjects.has(project.id)
                      return (
                        <div
                          key={project.id}
                          className="group flex h-11 w-full items-center rounded-md transition-colors hover:bg-(--bg-key)"
                        >
                          <button
                            type="button"
                            onClick={() => {
                              saveLastAimProject(project.id)
                              navigate({
                                to: '/aim/$projectId/$feature',
                                params: { projectId: project.id, feature: 'overview' },
                              })
                              onMobileClose?.()
                            }}
                            className="flex h-full min-w-0 flex-1 items-center gap-2 px-1.5 text-left"
                            title={getRulebookId(project) ? `${project.name} · ${getRulebookId(project)}` : project.name}
                          >
                            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-(--bg-key) text-(--color-text-muted) transition-colors group-hover:text-(--color-text)">
                              <FolderKanban size={13} aria-hidden="true" />
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-xs font-medium text-(--color-text-2) group-hover:text-(--color-text)">
                                {project.name}
                              </span>
                              <span className="block truncate font-mono text-[9px] text-(--color-text-subtle)">
                                {getRulebookId(project) ?? 'No rulebook linked'}
                              </span>
                            </span>
                            {hasRunning ? (
                              <span className="flex shrink-0 items-center gap-1 text-[9px] font-medium text-(--color-accent)">
                                <Activity size={9} aria-hidden="true" />
                                Live
                              </span>
                            ) : (
                              <ChevronRight size={12} className="shrink-0 text-(--color-text-subtle) opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={() => setRemoveProjectTarget(project)}
                            disabled={removeProjectMutation.isPending}
                            className="mr-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-(--color-text-subtle) transition-colors hover:bg-(--color-error-subtle) hover:text-(--color-error) disabled:cursor-not-allowed disabled:opacity-40"
                            aria-label={`Remove project ${project.name} from AIM`}
                            title={`Remove ${project.name} from AIM`}
                          >
                            <Trash2 size={12} aria-hidden="true" />
                          </button>
                        </div>
                      )
                    })}
                  {activeProject && projects.length === 1 && (
                    <p className="px-1.5 py-2 text-[11px] text-(--color-text-subtle)">
                      No other projects
                    </p>
                  )}
                </div>
              </section>
            </div>
          )}
        </nav>

        {/* Footer trio — mirrors the forge/coding sidebars so all three
            modes feel like the same shell. */}
        <SidebarShellDivider />
        <SidebarFooter onCommandPalette={onCommandPalette} onAction={onMobileClose} />
      </SidebarCard>
  )

  const removeProjectDialog = (
    <Dialog
      open={removeProjectTarget !== null}
      onOpenChange={(open) => {
        if (!open) setRemoveProjectTarget(null)
      }}
    >
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>Remove project from AIM?</DialogTitle>
          <DialogDescription>
            {removeProjectTarget
              ? `Remove ${removeProjectTarget.name} from AIM? Source, target, and document folders will remain on disk.`
              : 'Remove this project from AIM? Its folders will remain on disk.'}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="p-3">
          <Button
            type="button"
            variant="outline"
            onClick={() => setRemoveProjectTarget(null)}
            disabled={removeProjectMutation.isPending}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={!removeProjectTarget || removeProjectMutation.isPending}
            onClick={() => {
              const target = removeProjectTarget
              if (!target) return
              const nextProject = projects.find((project) => project.id !== target.id)
              removeProjectMutation.mutate(target.id, {
                onSuccess: () => {
                  if (activeProjectId === target.id) {
                    if (nextProject) {
                      saveLastAimProject(nextProject.id)
                      navigate({
                        to: '/aim/$projectId/$feature',
                        params: { projectId: nextProject.id, feature: 'overview' },
                        replace: true,
                      })
                    } else {
                      clearLastAimProject()
                      navigate({ to: '/aim', replace: true })
                    }
                  }
                  setRemoveProjectTarget(null)
                  onMobileClose?.()
                },
                onError: (error) => {
                  useToastStore.getState().push({
                    tone: 'error',
                    title: "Couldn't remove project",
                    description: error instanceof Error ? error.message : String(error),
                  })
                },
              })
            }}
          >
            {removeProjectMutation.isPending ? 'Removing...' : 'Remove from AIM'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )

  if (mobile) {
    return (
      <>
        <div className="h-full w-full overflow-hidden p-1">{content}</div>
        {removeProjectDialog}
      </>
    )
  }

  return (
    <>
      <SidebarShell
        collapsed={collapsed}
        rail={rail}
        resizeLabel="Resize AIM sidebar"
      >
        {content}
      </SidebarShell>
      {removeProjectDialog}
    </>
  )
}

function getRulebookId(project: {
  settings?: Record<string, unknown> | null
}): string | undefined {
  return (
    project.settings?.aim as { rulebook?: { id?: string } } | undefined
  )?.rulebook?.id
}

function AimProjectListSkeleton() {
  return (
    <div className="px-1" aria-label="Loading AIM projects">
      <div className="mb-2 flex items-center justify-between">
        <Skeleton className="h-2.5 w-24" />
        <Skeleton className="h-4 w-12 rounded-full" />
      </div>
      <div className="flex items-center gap-2.5 pb-2.5">
        <Skeleton className="h-8 w-8 shrink-0 rounded-md" />
        <div className="min-w-0 flex-1 space-y-1.5">
          <Skeleton className="h-3 w-2/3" />
          <Skeleton className="h-2 w-4/5" />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-1">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} className="h-9 rounded-md" />
        ))}
      </div>
      <div className="mb-2 mt-4 border-t border-(--color-border) pt-3">
        <Skeleton className="h-2.5 w-24" />
      </div>
      {Array.from({ length: 4 }, (_, index) => (
        <div key={index} className="flex h-11 items-center gap-2 px-1.5">
          <Skeleton className="h-7 w-7 shrink-0 rounded-md" />
          <div className="min-w-0 flex-1 space-y-1.5">
            <Skeleton className="h-2.5" style={{ width: `${52 + (index % 3) * 13}%` }} />
            <Skeleton className="h-2 w-2/5" />
          </div>
        </div>
      ))}
    </div>
  )
}
