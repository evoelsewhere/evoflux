/** TanStack Query hook for the slash-command picker. */
import { useQuery } from '@tanstack/react-query'

import { listCommands } from '@/api/client'

import { queryKeys } from './keys'

export function useCommandsQuery(workspace?: string | null) {
  return useQuery({
    queryKey: queryKeys.commands.list(workspace),
    queryFn: () => listCommands(workspace),
    // Commands live on disk and rarely change during a session.
    staleTime: 60_000,
  })
}
