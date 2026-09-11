import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  dismissLanguageServerInstallError,
  getLanguageServers,
  installLanguageServer,
} from '@/api/client'
import { queryKeys } from './keys'

/**
 * Language-server status. While any install is running the overview is the only
 * place its progress lives, so the query polls until none are.
 */
export function useLanguageServersQuery(workspaces: readonly string[]) {
  return useQuery({
    queryKey: queryKeys.settings.languageServers(workspaces),
    queryFn: () => getLanguageServers(workspaces),
    staleTime: 15_000,
    refetchInterval: (query) =>
      query.state.data?.servers.some((server) => server.install_phase === 'running')
        ? 2_000
        : false,
  })
}

export function useInstallLanguageServerMutation(workspaces: readonly string[]) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: installLanguageServer,
    // The install has only started; re-reading picks up the running phase so
    // the row reports it even if the user navigates away and comes back.
    onSettled: () => client.invalidateQueries({
      queryKey: queryKeys.settings.languageServers(workspaces),
    }),
  })
}

export function useDismissLanguageServerErrorMutation(workspaces: readonly string[]) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: dismissLanguageServerInstallError,
    onSettled: () => client.invalidateQueries({
      queryKey: queryKeys.settings.languageServers(workspaces),
    }),
  })
}
