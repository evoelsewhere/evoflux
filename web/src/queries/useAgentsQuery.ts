import { useQuery } from '@tanstack/react-query'
import { listTeamAgents } from '@/api/client'
import { queryKeys } from './keys'

/** Team mode — GET /team/agents. `mode` picks the roster for a
 * workspace-bound team ('coding'); omit for the work team. */
export function useTeamAgentsQuery(
  workspace?: string | null,
  enabled = true,
  mode?: 'coding' | null,
) {
  return useQuery({
    queryKey: queryKeys.teamAgents(workspace, mode),
    queryFn: () => listTeamAgents(workspace, mode),
    enabled,
    staleTime: 30_000,
  })
}
