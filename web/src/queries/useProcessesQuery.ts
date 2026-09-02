import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getProcesses, terminateProcess } from '@/api/client'
import { queryKeys } from './keys'

export function useProcessesQuery(enabled = true) {
  return useQuery({
    queryKey: queryKeys.team.processes(),
    queryFn: getProcesses,
    enabled,
    refetchInterval: enabled ? 2_000 : false,
  })
}

export function useTerminateProcessMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: terminateProcess,
    onSuccess: () => queryClient.invalidateQueries({
      queryKey: queryKeys.team.processes(),
    }),
  })
}
