import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getLanguageServers, installLanguageServer } from '@/api/client'
import { queryKeys } from './keys'

export function useLanguageServersQuery(workspaces: readonly string[]) {
  return useQuery({
    queryKey: queryKeys.settings.languageServers(workspaces),
    queryFn: () => getLanguageServers(workspaces),
    staleTime: 15_000,
  })
}

export function useInstallLanguageServerMutation(workspaces: readonly string[]) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: installLanguageServer,
    onSuccess: async () => {
      await client.invalidateQueries({
        queryKey: queryKeys.settings.languageServers(workspaces),
      })
    },
  })
}
