/** TanStack Query hook for the coding-workspace snippet picker. */
import { useQuery } from '@tanstack/react-query'

import { listSnippets } from '@/api/client'

import { queryKeys } from './keys'

export function useSnippetsQuery(workspace: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.snippets.list(workspace ?? ''),
    queryFn: () => listSnippets(workspace ?? ''),
    enabled: Boolean(workspace),
    staleTime: 60_000,
  })
}
