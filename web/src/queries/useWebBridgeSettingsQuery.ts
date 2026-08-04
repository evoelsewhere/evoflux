import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getWebBridgeSettings,
  updateWebBridgeSettings,
  type WebBridgeSettings,
} from '@/api/client'
import { queryKeys } from './keys'

export function useWebBridgeSettingsQuery() {
  return useQuery({
    queryKey: queryKeys.settings.webbridge(),
    queryFn: getWebBridgeSettings,
    staleTime: 30_000,
  })
}

export function useUpdateWebBridgeSettingsMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: WebBridgeSettings) => updateWebBridgeSettings(body),
    onSuccess: (data) => {
      client.setQueryData(queryKeys.settings.webbridge(), data)
    },
  })
}
