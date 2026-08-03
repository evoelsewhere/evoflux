import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from '@tanstack/react-router'
import { AnimatePresence, motion } from 'framer-motion'
import { Menu } from 'lucide-react'
import { AimSidebar } from '@/components/AimSidebar'
import { AIM_FEATURES, loadLastAimProject, saveLastAimProject } from '@/lib/aim-sidebar'
import { AimSetupWizard } from '@/components/AimSetupWizard'
import { AimOverviewPanel } from '@/components/AimOverviewPanel'
import { AimPipelinesPanel } from '@/components/AimPipelinesPanel'
import { AimKbPanel } from '@/components/AimKbPanel'
import { AimTraceabilityPanel } from '@/components/AimTraceabilityPanel'
import { CommandPalette, type Command } from '@/components/CommandPalette'
import { AppShell } from '@/components/shell/AppShell'
import { MobileDrawerBackdrop } from '@/components/shell/MobileDrawerBackdrop'
import { Skeleton } from '@/components/ui/skeleton'
import { useAimProjectsQuery } from '@/queries/useAimProjectsQuery'
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts'
import { useIsMobile } from '@/hooks/use-mobile'
import { useModalFocus } from '@/hooks/useModalFocus'
import { useMotionPreset } from '@/lib/motion'
import { useUIStore } from '@/stores/useUIStore'
import { errorMessage } from '@/utils/errors'
import type { AimFeature } from '@/lib/aim-sidebar'
import type { CodingProject } from '@/api/types'

/**
 * Layout for /aim, /aim/$projectId, /aim/$projectId/$feature and
 * /aim/$projectId/runs/$runId — the AIM mode shell
 * (aim-mode-shell-ux-spec.md v2.2): AimSidebar navigation on the left,
 * the selected project feature as the main content. Deliberately NOT built
 * around TeamChatView — there is no chat surface in this mode; the only
 * chat entry point is the post-run Discussion panel (FE-3). The frame
 * (outer container, sidebar toggle, <main> card) is the shared AppShell,
 * so switching modes doesn't visibly change the chrome.
 */
function AimLayoutBase() {
  const params = useParams({ strict: false }) as Record<string, string>
  const projectId = params.projectId as string | undefined
  const rawFeature = params.feature as string | undefined
  // /aim/$projectId/runs/$runId — deep link to one run's report (§3.2).
  // Runs & Reports folded into Pipelines: this URL still works, it just
  // opens the Report side panel on the Pipelines screen now.
  const runId = params.runId as string | undefined
  const navigate = useNavigate()
  const [wizardOpen, setWizardOpen] = useState(false)
  const [showPalette, setShowPalette] = useState(false)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const isMobile = useIsMobile()
  const preset = useMotionPreset()
  useModalFocus(isMobile && mobileSidebarOpen, () => setMobileSidebarOpen(false))

  // Ctrl+P — same palette shortcut as the other two modes (shared hook).
  // Ctrl+B (sidebar collapse) is registered once by AppShell.
  useKeyboardShortcuts({
    p: () => setShowPalette((v) => !v),
  })

  const projectsQuery = useAimProjectsQuery()
  const projects = projectsQuery.data
  const project = projects?.find((p) => p.id === projectId)

  // Command palette — jump straight to any project's feature screen, or
  // open/toggle the same actions the sidebar itself exposes (§ search).
  const commands = useMemo<Command[]>(() => {
    const projectCommands = (projects ?? []).flatMap((p) =>
      AIM_FEATURES.map((f) => ({
        id: `${p.id}-${f.key}`,
        group: 'Navigation',
        label: `${p.name} · ${f.label}`,
        description: 'AIM project',
        action: () => {
          saveLastAimProject(p.id)
          navigate({ to: '/aim/$projectId/$feature', params: { projectId: p.id, feature: f.key } })
        },
      })),
    )
    return [
      ...projectCommands,
      { id: 'new-project', group: 'AIM', label: 'New / Join Project', description: 'Set up a migration project', action: () => setWizardOpen(true) },
      { id: 'toggle-sidebar', group: 'View', label: 'Toggle Sidebar', description: '', shortcut: 'Ctrl+B', action: () => useUIStore.getState().toggleSidebarCollapsed() },
      { id: 'go-settings', group: 'Settings', label: 'Open Settings', description: 'Manage agents & skills', action: () => useUIStore.getState().openSettings('agents') },
    ]
  }, [projects, navigate])

  const feature: AimFeature = runId
    ? 'pipelines'
    : rawFeature === 'rulebook'
      ? 'traceability'
    : AIM_FEATURES.some((f) => f.key === rawFeature)
      ? (rawFeature as AimFeature)
      : 'overview'

  // Bare /aim — restore the last-open project once the list is known.
  useEffect(() => {
    if (projectId || !projects) return
    const lastId = loadLastAimProject()
    const target = projects.find((p) => p.id === lastId) ?? projects[0]
    if (target) {
      navigate({
        to: '/aim/$projectId/$feature',
        params: { projectId: target.id, feature: 'overview' },
        replace: true,
      })
    }
  }, [projectId, projects, navigate])

  // /aim/$projectId without a feature (or with an unknown one) → overview.
  // A run deep-link (`runs/$runId`) has no $feature param — leave it alone.
  useEffect(() => {
    if (!projectId || runId || rawFeature === feature) return
    navigate({
      to: '/aim/$projectId/$feature',
      params: { projectId, feature },
      replace: true,
    })
  }, [projectId, rawFeature, runId, feature, navigate])

  useEffect(() => {
    if (projectId && project) saveLastAimProject(projectId)
  }, [projectId, project])

  return (
    <AppShell
      sidebar={!isMobile ? (
        <AimSidebar
          activeProjectId={projectId}
          activeFeature={projectId ? feature : undefined}
          onNewProject={() => setWizardOpen(true)}
          onCommandPalette={() => setShowPalette(true)}
        />
      ) : null}
      mobileSidebar={
        isMobile ? (
          <>
            <AnimatePresence>
              {mobileSidebarOpen && (
                <MobileDrawerBackdrop
                  onClose={() => setMobileSidebarOpen(false)}
                  closeLabel="Close AIM navigation"
                />
              )}
            </AnimatePresence>
            <AnimatePresence>
              {mobileSidebarOpen && (
                <motion.aside
                  key="aim-drawer-panel"
                  aria-label="AIM navigation"
                  aria-modal="true"
                  data-modal-focus="true"
                  className="mobile-safe-top fixed bottom-0 left-0 z-(--z-overlay) w-[min(288px,calc(100vw-2rem))] overflow-hidden bg-(--bg-sidebar) shadow-xl md:hidden"
                  initial={{ x: '-100%' }}
                  animate={{ x: 0 }}
                  exit={{ x: '-100%' }}
                  transition={preset.spring}
                >
                  <AimSidebar
                    activeProjectId={projectId}
                    activeFeature={projectId ? feature : undefined}
                    onNewProject={() => setWizardOpen(true)}
                    onCommandPalette={() => setShowPalette(true)}
                    mobile
                    onMobileClose={() => setMobileSidebarOpen(false)}
                  />
                </motion.aside>
              )}
            </AnimatePresence>
          </>
        ) : null
      }
      header={
        isMobile ? (
          <div className="mobile-safe-header flex h-11 shrink-0 items-center gap-2 border-b border-(--color-border) bg-(--bg-page) px-2 md:hidden">
            <button
              type="button"
              onClick={() => setMobileSidebarOpen(true)}
              aria-label="Open AIM navigation"
              className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
            >
              <Menu size={16} />
            </button>
            <span className="min-w-0 flex-1 truncate text-xs font-medium text-(--color-text)">
              {project?.name ?? 'AIM'}
            </span>
            {project && (
              <span className="text-[10px] text-(--color-text-subtle)">
                {AIM_FEATURES.find((item) => item.key === feature)?.label}
              </span>
            )}
          </div>
        ) : null
      }
      overlay={
        <>
          <AimSetupWizard
            open={wizardOpen}
            onOpenChange={setWizardOpen}
            onCreated={(id) =>
              navigate({ to: '/aim/$projectId/$feature', params: { projectId: id, feature: 'overview' } })
            }
          />
          {showPalette && (
            <CommandPalette commands={commands} onClose={() => setShowPalette(false)} />
          )}
        </>
      }
    >
      {!projectId || !project ? (
        <EmptyState
          loading={projectsQuery.isLoading}
          error={projectsQuery.isError ? projectsQuery.error : null}
          onRetry={() => void projectsQuery.refetch()}
          hasProjects={(projects?.length ?? 0) > 0}
          notFound={Boolean(projectId) && !projectsQuery.isLoading && !projectsQuery.isError && !project}
          onNewProject={() => setWizardOpen(true)}
        />
      ) : (
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={`${project.id}:${feature}:${runId ?? ''}`}
            className="flex h-full min-h-0 flex-1 flex-col"
            initial={{ opacity: 0, y: 6 * preset.distance }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 * preset.distance }}
            transition={preset.transition}
          >
            <FeaturePanel project={project} feature={feature} runId={runId} />
          </motion.div>
        </AnimatePresence>
      )}
    </AppShell>
  )
}

function EmptyState({
  loading,
  error,
  onRetry,
  hasProjects,
  notFound,
  onNewProject,
}: {
  loading: boolean
  error: unknown
  onRetry: () => void
  hasProjects: boolean
  notFound: boolean
  onNewProject: () => void
}) {
  if (loading) {
    return (
      <div className="h-full p-4" aria-label="Loading AIM project">
        <div className="mx-auto w-full max-w-5xl space-y-4">
          <div className="flex items-center justify-between gap-4 border-b border-(--color-border) pb-3">
            <Skeleton className="h-4 w-36" />
            <Skeleton className="h-8 w-48" />
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {Array.from({ length: 4 }, (_, index) => (
              <div key={index} className="space-y-2 rounded-md border border-(--color-border) p-3">
                <Skeleton className="h-2.5 w-16" />
                <Skeleton className="h-6 w-12" />
              </div>
            ))}
          </div>
          <div className="grid gap-3 md:grid-cols-[2fr_1fr]">
            <div className="space-y-3 rounded-md border border-(--color-border) p-3">
              <Skeleton className="h-3 w-28" />
              {Array.from({ length: 5 }, (_, index) => (
                <Skeleton key={index} className="h-10 w-full" />
              ))}
            </div>
            <div className="space-y-3 rounded-md border border-(--color-border) p-3">
              <Skeleton className="h-3 w-24" />
              {Array.from({ length: 4 }, (_, index) => (
                <Skeleton key={index} className="h-12 w-full" />
              ))}
            </div>
          </div>
        </div>
      </div>
    )
  }

  // A failed projects request must not read as "you have no projects" — that
  // looks like data loss and hides the retry path.
  if (error) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-sm text-center">
          <p className="text-sm font-medium text-(--color-text)">Failed to load migration projects</p>
          <p className="mt-1 text-xs leading-5 text-(--color-text-muted)">{errorMessage(error)}</p>
          <button
            type="button"
            onClick={onRetry}
            className="focus-ring-control mt-3 rounded-md border border-(--color-border) bg-(--bg-key) px-3 py-1.5 text-xs font-medium text-(--color-text) hover:bg-(--bg-page)"
          >
            Try again
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center">
        <p className="text-sm text-(--color-text-muted)">
          {notFound
              ? 'Project not found.'
              : hasProjects
                ? 'Pick a project from the sidebar.'
                : 'No migration projects yet.'}
        </p>
        {!loading && !hasProjects && (
          <button
            type="button"
            onClick={onNewProject}
            className="mt-3 rounded-md border border-(--color-border) bg-(--bg-key) px-3 py-1.5 text-xs font-medium text-(--color-text) hover:bg-(--bg-page)"
          >
            New / Join project
          </button>
        )}
      </div>
    </div>
  )
}

function FeaturePanel({
  project,
  feature,
  runId,
}: {
  project: CodingProject
  feature: AimFeature
  runId?: string
}) {
  switch (feature) {
    case 'overview':
      return <AimOverviewPanel project={project} />
    case 'pipelines':
      return <AimPipelinesPanel project={project} runId={runId} />
    case 'kb':
      return <AimKbPanel project={project} />
    case 'traceability':
      return <AimTraceabilityPanel project={project} />
  }
}

export function AimLayout() {
  return <AimLayoutBase />
}
