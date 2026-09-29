/**
 * CodingStartHero — the bare `/coding` page.
 *
 * Coding is project-only, so the first action is the project the user was
 * last in (the one the sidebar already shows selected): starting a chat
 * there is one click. Opening a folder as a new project stays next to it.
 */
import { useNavigate } from '@tanstack/react-router'
import { FolderPlus, Plus } from 'lucide-react'

import { WelcomeHero } from '@/components/ChatWelcome'
import { Button } from '@/components/ui/button'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { useCodingOverviewQuery } from '@/queries/useProjectsQuery'
import { useTeamStore } from '@/stores/useTeamStore'
import { useUIStore } from '@/stores/useUIStore'
import { saveLastCodingFocus } from '@/utils/workspace'

function readLastCodingProjectId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEYS.coding.lastProject) || null
  } catch {
    return null
  }
}

export function CodingStartHero({ onOpenFolder }: { onOpenFolder: () => void }) {
  const navigate = useNavigate()
  const projects = useCodingOverviewQuery().data?.projects ?? []
  // The sidebar's selection, as it stands now; the remembered last project
  // only until the sidebar has settled (or on a phone, where it may be closed).
  const sidebarProjectId = useUIStore((state) => state.codingSelectedProjectId)
  const projectId = sidebarProjectId ?? readLastCodingProjectId()
  const project =
    projects.find((item) => item.id === projectId && item.workspaces.length > 0)
    ?? null

  const startInProject = () => {
    if (!project) return
    const state = useTeamStore.getState()
    state.beginResolvedSession(null, {
      mode: 'coding',
      // The project's primary repo, same first entry the backend derives.
      workspace: project.workspaces[0]?.path ?? null,
      projectId: project.id,
      model: state.sessionId ? state.sessionModel : null,
      thinkingLevel: state.sessionId ? state.sessionThinkingLevel : null,
    })
    saveLastCodingFocus({ project_id: project.id })
    navigate({ to: '/coding/$focusId', params: { focusId: project.id } })
  }

  return (
    <WelcomeHero
      icon={<FolderPlus size={20} strokeWidth={1.8} aria-hidden="true" />}
      title="Start with a project"
      description="Pick a project in the sidebar, or open a repository folder to make one. A project gives your coding team its files, source control and context."
    >
      {project && (
        <Button type="button" size="sm" className="h-8 rounded-lg px-3.5 text-xs" onClick={startInProject}>
          <Plus size={14} aria-hidden="true" />
          <span>
            New chat in <span data-i18n-ignore>{project.name}</span>
          </span>
        </Button>
      )}
      <Button
        type="button"
        size="sm"
        variant={project ? 'outline' : 'default'}
        className="h-8 rounded-lg px-3.5 text-xs"
        onClick={onOpenFolder}
      >
        <FolderPlus size={14} aria-hidden="true" />
        Open folder as project
      </Button>
    </WelcomeHero>
  )
}
