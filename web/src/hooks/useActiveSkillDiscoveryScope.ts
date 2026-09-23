import { useMemo } from 'react'

import type { SkillDiscoveryScope } from '@/api/client'
import { useProjectQuery } from '@/queries/useProjectsQuery'
import { useTeamStore } from '@/stores/useTeamStore'

/**
 * Scope skill discovery to every active project repo, or the current single
 * repo. Skills are available in every mode, so the scope is workspaces only.
 */
export function useActiveSkillDiscoveryScope(): SkillDiscoveryScope {
  const activeWorkspace = useTeamStore((state) => state._workspace)
  const projectId = useTeamStore((state) => state.projectId)
  const project = useProjectQuery(projectId)
  return useMemo(
    () => ({
      workspaces: project.data?.workspaces.length
        ? project.data.workspaces.map((workspace) => workspace.path)
        : activeWorkspace
          ? [activeWorkspace]
          : [],
    }),
    [activeWorkspace, project.data],
  )
}
