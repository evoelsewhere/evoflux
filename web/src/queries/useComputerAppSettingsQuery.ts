import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getComputerAppSettings,
  updateComputerAppSettings,
  type ComputerAppSettings,
} from '@/api/client'
import { queryKeys } from './keys'

export function useComputerAppSettingsQuery() {
  return useQuery({
    queryKey: queryKeys.settings.computerApp(),
    queryFn: getComputerAppSettings,
    staleTime: 30_000,
  })
}

export function useUpdateComputerAppSettingsMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: ComputerAppSettings) => updateComputerAppSettings(body),
    onSuccess: (data) => {
      client.setQueryData(queryKeys.settings.computerApp(), data)
    },
  })
}
