import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { listTeamAgents, listTeamLeads, updateTeamSessionLead } from '@/api/client'
import { queryKeys } from './keys'

/** Team mode — GET /team/agents. `mode` picks the roster for a
 * workspace-bound team ('coding'); omit for the work team. */
export function useTeamAgentsQuery(
  workspace?: string | null,
  enabled = true,
  mode?: 'coding' | null,
  sessionId?: string | null,
) {
  return useQuery({
    queryKey: queryKeys.teamAgents(workspace, mode, sessionId),
    queryFn: () => listTeamAgents(workspace, mode, sessionId),
    enabled,
    staleTime: 30_000,
  })
}

export function useTeamLeadsQuery(mode: 'work' | 'coding', enabled = true) {
  return useQuery({
    queryKey: queryKeys.team.leads(mode),
    queryFn: () => listTeamLeads(mode),
    enabled,
    staleTime: 10_000,
  })
}

export function useUpdateTeamSessionLeadMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ sessionId, leadName }: { sessionId: string; leadName: string }) =>
      updateTeamSessionLead(sessionId, leadName),
    onSuccess: (session) => {
      client.setQueryData(queryKeys.team.sessions.metadata(session.id), session)
      void client.invalidateQueries({ queryKey: queryKeys.team.status() })
      void client.invalidateQueries({ queryKey: ['agents', 'team'] })
    },
  })
}
