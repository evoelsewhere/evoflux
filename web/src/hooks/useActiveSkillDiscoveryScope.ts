import { useMemo } from 'react'

import type { SkillDiscoveryScope } from '@/api/client'
import type { SkillMode } from '@/api/types'
import { useProjectQuery } from '@/queries/useProjectsQuery'
import { useTeamStore } from '@/stores/useTeamStore'

/** Scope skill discovery to every active project repo, or the current single repo. */
export function useActiveSkillDiscoveryScope(
  mode?: SkillMode | null,
): SkillDiscoveryScope {
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
      mode: mode ?? null,
    }),
    [activeWorkspace, mode, project.data],
  )
}
