import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from '@tanstack/react-router'
import { PanelLeft } from 'lucide-react'
import { AimSidebar, AIM_FEATURES, loadLastAimProject, saveLastAimProject } from '@/components/AimSidebar'
import { AimSetupWizard } from '@/components/AimSetupWizard'
import { AimOverviewPanel } from '@/components/AimOverviewPanel'
import { AimPipelinesPanel } from '@/components/AimPipelinesPanel'
import { AimKbPanel } from '@/components/AimKbPanel'
import { AimRulebookPanel } from '@/components/AimRulebookPanel'
import { useAimProjectsQuery } from '@/queries/useAimProjectsQuery'
import type { AimFeature } from '@/components/AimSidebar'
import type { CodingProject } from '@/api/types'

const AIM_SIDEBAR_COLLAPSE_KEY = 'oa-aim-sidebar-collapsed'

/**
 * Layout for /aim, /aim/$projectId, /aim/$projectId/$feature and
 * /aim/$projectId/runs/$runId — the AIM mode shell
 * (aim-mode-shell-ux-spec.md v2.2): AimSidebar navigation on the left,
 * the selected project feature as the main content. Deliberately NOT built
 * around TeamChatView — there is no chat surface in this mode; the only
 * chat entry point is the post-run Discussion panel (FE-3). The shell
 * chrome (outer flex + toggle + rounded shadowed main panel) mirrors
 * TeamChatView's so switching modes doesn't visibly change the frame.
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
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(AIM_SIDEBAR_COLLAPSE_KEY) === 'true'
    } catch {
      return false
    }
  })

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem(AIM_SIDEBAR_COLLAPSE_KEY, String(next))
      } catch {
        // ignore storage failures
      }
      return next
    })
  }, [])

  // Ctrl+B — same collapse shortcut as the other two modes.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!e.ctrlKey || e.metaKey) return
      if (e.key === 'b') {
        e.preventDefault()
        toggleSidebar()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [toggleSidebar])

  const projectsQuery = useAimProjectsQuery()
  const projects = projectsQuery.data
  const project = projects?.find((p) => p.id === projectId)

  const feature: AimFeature = runId
    ? 'pipelines'
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
      params: { projectId, feature: 'overview' },
      replace: true,
    })
  }, [projectId, rawFeature, runId, feature, navigate])

  useEffect(() => {
    if (projectId && project) saveLastAimProject(projectId)
  }, [projectId, project])

  return (
    <div className="mobile-safe-shell mobile-viewport flex h-dvh flex-col bg-(--bg-page) md:flex-row md:gap-0.5 md:p-1">
      <AimSidebar
        activeProjectId={projectId}
        activeFeature={projectId ? feature : undefined}
        onNewProject={() => setWizardOpen(true)}
        collapsed={sidebarCollapsed}
      />

      {/* Sidebar toggle — same placement + affordance as the other modes. */}
      <div className="flex shrink-0 flex-col items-center pt-2">
        <button
          type="button"
          onClick={toggleSidebar}
          aria-label="Toggle sidebar"
          title="Toggle sidebar (Ctrl+B)"
          className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
        >
          <PanelLeft size={15} aria-hidden="true" />
        </button>
      </div>

      <main className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        {!projectId || !project ? (
          <EmptyState
            loading={projectsQuery.isLoading}
            hasProjects={(projects?.length ?? 0) > 0}
            notFound={Boolean(projectId) && !projectsQuery.isLoading && !project}
            onNewProject={() => setWizardOpen(true)}
          />
        ) : (
          <FeaturePanel project={project} feature={feature} runId={runId} />
        )}
      </main>

      <AimSetupWizard
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        onCreated={(id) =>
          navigate({ to: '/aim/$projectId/$feature', params: { projectId: id, feature: 'overview' } })
        }
      />
    </div>
  )
}

function EmptyState({
  loading,
  hasProjects,
  notFound,
  onNewProject,
}: {
  loading: boolean
  hasProjects: boolean
  notFound: boolean
  onNewProject: () => void
}) {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center">
        <p className="text-sm text-(--color-text-muted)">
          {loading
            ? 'Loading projects…'
            : notFound
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
    case 'rulebook':
      return <AimRulebookPanel project={project} />
  }
}

export function AimLayout() {
  return <AimLayoutBase />
}
