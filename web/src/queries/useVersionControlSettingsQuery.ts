import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getVersionControlSettings,
  updateVersionControlSettings,
  type VersionControlSettings,
} from '@/api/client'
import { queryKeys } from './keys'

export function useVersionControlSettingsQuery() {
  return useQuery({
    queryKey: queryKeys.settings.versionControl(),
    queryFn: getVersionControlSettings,
    staleTime: 30_000,
  })
}

export function useUpdateVersionControlSettingsMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: VersionControlSettings) =>
      updateVersionControlSettings(body),
    onSuccess: (data) => {
      client.setQueryData(queryKeys.settings.versionControl(), data)
    },
  })
}
