import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from '@tanstack/react-router'
import { AimSidebar } from '@/components/AimSidebar'
import { AIM_FEATURES, loadLastAimProject, saveLastAimProject } from '@/lib/aim-sidebar'
import { AimSetupWizard } from '@/components/AimSetupWizard'
import { AimOverviewPanel } from '@/components/AimOverviewPanel'
import { AimPipelinesPanel } from '@/components/AimPipelinesPanel'
import { AimKbPanel } from '@/components/AimKbPanel'
import { AimRulebookPanel } from '@/components/AimRulebookPanel'
import { CommandPalette, type Command } from '@/components/CommandPalette'
import { AppShell } from '@/components/shell/AppShell'
import { useAimProjectsQuery } from '@/queries/useAimProjectsQuery'
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts'
import { useUIStore } from '@/stores/useUIStore'
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
    <AppShell
      sidebar={
        <AimSidebar
          activeProjectId={projectId}
          activeFeature={projectId ? feature : undefined}
          onNewProject={() => setWizardOpen(true)}
          onCommandPalette={() => setShowPalette(true)}
        />
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
          hasProjects={(projects?.length ?? 0) > 0}
          notFound={Boolean(projectId) && !projectsQuery.isLoading && !project}
          onNewProject={() => setWizardOpen(true)}
        />
      ) : (
        <FeaturePanel project={project} feature={feature} runId={runId} />
      )}
    </AppShell>
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
