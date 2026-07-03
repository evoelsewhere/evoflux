import { useQuery } from '@tanstack/react-query'
import { listTeamAgents } from '@/api/client'
import { queryKeys } from './keys'

/** Team mode — GET /team/agents */
export function useTeamAgentsQuery(workspace?: string | null, enabled = true) {
  return useQuery({
    queryKey: queryKeys.teamAgents(workspace),
    queryFn: () => listTeamAgents(workspace),
    enabled,
    staleTime: 30_000,
  })
}
