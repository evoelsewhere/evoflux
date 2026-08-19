import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getConductorStatus, syncConductor } from '@/api/client'
import { queryKeys } from '@/queries/keys'

export function useConductorStatusQuery() {
  return useQuery({
    queryKey: queryKeys.settings.conductorStatus(),
    queryFn: getConductorStatus,
    staleTime: 5_000,
    refetchInterval: 10_000,
  })
}

export function useSyncConductorMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: syncConductor,
    onSuccess: (status) => {
      queryClient.setQueryData(queryKeys.settings.conductorStatus(), status)
    },
  })
}
