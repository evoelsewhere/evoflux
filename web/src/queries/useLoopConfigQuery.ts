import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getLoopConfig,
  putLoopConfig,
} from '@/api/client'
import type { LoopConfig } from '@/api/client'
import { queryKeys } from './keys'

export function useLoopConfigQuery() {
  return useQuery({
    queryKey: queryKeys.loop.config(),
    queryFn: getLoopConfig,
  })
}

export function useUpdateLoopConfigMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (config: LoopConfig) => putLoopConfig(config),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.loop.config() })
    },
  })
}
