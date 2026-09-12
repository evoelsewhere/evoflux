import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getFollowUpSettings,
  updateFollowUpSettings,
  type FollowUpSettings,
} from '@/api/client'
import { queryKeys } from './keys'

export function useFollowUpSettingsQuery() {
  return useQuery({
    queryKey: queryKeys.settings.followUp(),
    queryFn: getFollowUpSettings,
    staleTime: 30_000,
  })
}

export function useUpdateFollowUpSettingsMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: FollowUpSettings) => updateFollowUpSettings(body),
    onSuccess: (data) => {
      client.setQueryData(queryKeys.settings.followUp(), data)
    },
  })
}
