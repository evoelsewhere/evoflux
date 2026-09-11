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
  const queryKey = queryKeys.teamAgents(workspace, mode, sessionId)
  return useQuery({
    queryKey,
    queryFn: () => listTeamAgents(workspace, mode, sessionId),
    enabled,
    staleTime: 30_000,
    // One transition only: a draft acquiring its session id. The session id
    // is in the key because a session can override its roster, and a new key
    // means no cached data means `isLoading` — which makes the coding view
    // swap itself for its "Opening coding workspace" state for the length of
    // one round trip, right as the user presses send. Carrying the previous
    // answer across that one step keeps `isLoading` false and the view still.
    //
    // Deliberately not "any session id change": switching between two
    // sessions of the same repo can mean two different leads, and showing
    // the outgoing one for a round trip would be a stale-data bug traded for
    // a flicker. A session that has just been created has no override to be
    // stale about — the two answers are the same roster.
    placeholderData: (previous, previousQuery) =>
      previousQuery && isSessionIdArriving(previousQuery.queryKey, queryKey)
        ? previous
        : undefined,
  })
}

/**
 * True when two team-agent keys are identical except that the earlier one
 * had no session id and the later one does.
 */
function isSessionIdArriving(before: readonly unknown[], after: readonly unknown[]): boolean {
  if (before.length !== after.length) return false
  if (before.at(-1) !== null || after.at(-1) === null) return false
  return before.slice(0, -1).every((part, i) => part === after[i])
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
