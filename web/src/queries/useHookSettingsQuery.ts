import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getHookSettings,
  revokeSettingsHookTrust,
  saveSettingsHookWorkflowContent,
  trustSettingsHook,
  updateHookSettings,
} from '@/api/client'
import type { HookSettings, HookSettingsResponse } from '@/api/types'
import { queryKeys } from './keys'

export function useHookSettingsQuery() {
  return useQuery({
    queryKey: queryKeys.settings.hooks(),
    queryFn: getHookSettings,
    staleTime: 30_000,
  })
}

export function useUpdateHookSettingsMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: HookSettings) => updateHookSettings(body),
    onSuccess: (data: HookSettingsResponse) => {
      client.setQueryData(queryKeys.settings.hooks(), data)
    },
  })
}

export function useSaveSettingsHookWorkflowContentMutation() {
  return useMutation({
    mutationFn: ({ workflowId, content }: { workflowId: string; content: string }) =>
      saveSettingsHookWorkflowContent(workflowId, content),
  })
}

export function useTrustSettingsHookMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ hookId, digest }: { hookId: string; digest: string }) =>
      trustSettingsHook(hookId, digest),
    onSuccess: (data: HookSettingsResponse) => {
      client.setQueryData(queryKeys.settings.hooks(), data)
    },
  })
}

export function useRevokeSettingsHookTrustMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: revokeSettingsHookTrust,
    onSuccess: (data: HookSettingsResponse) => {
      client.setQueryData(queryKeys.settings.hooks(), data)
    },
  })
}
