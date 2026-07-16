import { useQuery } from '@tanstack/react-query'
import { listTeamAgents } from '@/api/client'
import { queryKeys } from './keys'

/** Team mode — GET /team/agents. `mode` picks the roster for a
 * workspace-bound team ('coding' | 'aim'); omit for the forge team. */
export function useTeamAgentsQuery(
  workspace?: string | null,
  enabled = true,
  mode?: 'coding' | 'aim' | null,
) {
  return useQuery({
    queryKey: queryKeys.teamAgents(workspace, mode),
    queryFn: () => listTeamAgents(workspace, mode),
    enabled,
    staleTime: 30_000,
  })
}
