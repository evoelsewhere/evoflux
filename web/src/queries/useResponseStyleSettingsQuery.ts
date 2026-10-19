import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getResponseStyleSettings,
  updateResponseStyleSettings,
  type ResponseStyleSettings,
} from '@/api/client'
import { queryKeys } from './keys'

export function useResponseStyleSettingsQuery() {
  return useQuery({
    queryKey: queryKeys.settings.responseStyle(),
    queryFn: getResponseStyleSettings,
    staleTime: 30_000,
  })
}

export function useUpdateResponseStyleSettingsMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: ResponseStyleSettings) => updateResponseStyleSettings(body),
    onSuccess: (data) => {
      client.setQueryData(queryKeys.settings.responseStyle(), data)
    },
  })
}
