import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getTeamSpawnSettings,
  updateTeamSpawnSettings,
  type TeamSpawnSettings,
} from '@/api/client'
import { queryKeys } from './keys'

export function useTeamSpawnSettingsQuery() {
  return useQuery({
    queryKey: queryKeys.settings.teamSpawn(),
    queryFn: getTeamSpawnSettings,
    staleTime: 30_000,
  })
}

export function useUpdateTeamSpawnSettingsMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: TeamSpawnSettings) => updateTeamSpawnSettings(body),
    onSuccess: (data) => {
      client.setQueryData(queryKeys.settings.teamSpawn(), data)
    },
  })
}
