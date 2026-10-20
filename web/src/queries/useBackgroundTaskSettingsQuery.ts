import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getBackgroundTaskSettings,
  updateBackgroundTaskSettings,
  type BackgroundTaskSettings,
} from '@/api/client'
import { queryKeys } from './keys'

export function useBackgroundTaskSettingsQuery() {
  return useQuery({
    queryKey: queryKeys.settings.backgroundTasks(),
    queryFn: getBackgroundTaskSettings,
    staleTime: 30_000,
  })
}

export function useUpdateBackgroundTaskSettingsMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: BackgroundTaskSettings) => updateBackgroundTaskSettings(body),
    onSuccess: (data) => {
      client.setQueryData(queryKeys.settings.backgroundTasks(), data)
    },
  })
}
