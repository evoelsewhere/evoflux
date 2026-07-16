import { useEffect, useState } from 'react'
import { useNavigate, useParams } from '@tanstack/react-router'
import { AimSidebar, AIM_FEATURES, loadLastAimProject, saveLastAimProject } from '@/components/AimSidebar'
import { AimSetupWizard } from '@/components/AimSetupWizard'
import { AimOverviewPanel } from '@/components/AimOverviewPanel'
import { AimPipelinesPanel } from '@/components/AimPipelinesPanel'
import { AimKbPanel } from '@/components/AimKbPanel'
import { AimRunsPanel } from '@/components/AimRunsPanel'
import { AimRulebookPanel } from '@/components/AimRulebookPanel'
import { useAimProjectsQuery } from '@/queries/useAimProjectsQuery'
import type { AimFeature } from '@/components/AimSidebar'
import type { CodingProject } from '@/api/types'

/**
 * Layout for /aim, /aim/$projectId, /aim/$projectId/$feature — the AIM mode
 * shell (aim-mode-shell-ux-spec.md v2.2): AimSidebar navigation on the left,
 * the selected project feature as the main content. Deliberately NOT built
 * around TeamChatView — there is no chat surface in this mode; the only
 * chat entry point is the post-run Discussion panel (FE-3).
 */
function AimLayoutBase() {
  const params = useParams({ strict: false }) as Record<string, string>
  const projectId = params.projectId as string | undefined
  const rawFeature = params.feature as string | undefined
  const navigate = useNavigate()
  const [wizardOpen, setWizardOpen] = useState(false)

  const projectsQuery = useAimProjectsQuery()
  const projects = projectsQuery.data
  const project = projects?.find((p) => p.id === projectId)

  const feature: AimFeature = AIM_FEATURES.some((f) => f.key === rawFeature)
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
  useEffect(() => {
    if (!projectId || rawFeature === feature) return
    navigate({
      to: '/aim/$projectId/$feature',
      params: { projectId, feature: 'overview' },
      replace: true,
    })
  }, [projectId, rawFeature, feature, navigate])

  useEffect(() => {
    if (projectId && project) saveLastAimProject(projectId)
  }, [projectId, project])

  return (
    <div className="flex h-dvh overflow-hidden bg-(--bg-page) md:gap-0.5 md:p-1">
      <AimSidebar
        activeProjectId={projectId}
        activeFeature={projectId ? feature : undefined}
        onNewProject={() => setWizardOpen(true)}
      />

      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-[10px] border border-(--color-border) bg-(--bg-card)">
        {!projectId || !project ? (
          <EmptyState
            loading={projectsQuery.isLoading}
            hasProjects={(projects?.length ?? 0) > 0}
            notFound={Boolean(projectId) && !projectsQuery.isLoading && !project}
            onNewProject={() => setWizardOpen(true)}
          />
        ) : (
          <FeaturePanel project={project} feature={feature} />
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

function FeaturePanel({ project, feature }: { project: CodingProject; feature: AimFeature }) {
  switch (feature) {
    case 'overview':
      return <AimOverviewPanel project={project} />
    case 'pipelines':
      return <AimPipelinesPanel project={project} />
    case 'kb':
      return <AimKbPanel project={project} />
    case 'runs':
      return <AimRunsPanel project={project} />
    case 'rulebook':
      return <AimRulebookPanel project={project} />
  }
}

export function AimLayout() {
  return <AimLayoutBase />
}
