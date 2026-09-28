import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getWebBridgeAgentBrowsing,
  getWebBridgeSettings,
  updateWebBridgeAgentBrowsing,
  updateWebBridgeSettings,
  type WebBridgeAgentBrowsing,
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

/** The composer's WebBridge toggle, saved on the server — not per chat. */
export function useWebBridgeAgentBrowsingQuery() {
  return useQuery({
    queryKey: queryKeys.settings.webbridgeAgentBrowsing(),
    queryFn: getWebBridgeAgentBrowsing,
    staleTime: 30_000,
  })
}

/**
 * Save the toggle. The backend reads it on every browser call, so flipping
 * it while an agent works redirects that agent's next browser action.
 * Optimistic, so every composer shows the new state at once.
 */
export function useUpdateWebBridgeAgentBrowsingMutation() {
  const client = useQueryClient()
  const key = queryKeys.settings.webbridgeAgentBrowsing()
  return useMutation({
    mutationFn: (enabled: boolean) => updateWebBridgeAgentBrowsing(enabled),
    onMutate: async (enabled) => {
      await client.cancelQueries({ queryKey: key })
      const previous = client.getQueryData<WebBridgeAgentBrowsing>(key)
      client.setQueryData<WebBridgeAgentBrowsing>(key, { enabled })
      return { previous }
    },
    onError: (_err, _enabled, context) => {
      if (context?.previous) client.setQueryData(key, context.previous)
    },
    onSuccess: (data) => {
      client.setQueryData(key, data)
    },
  })
}
