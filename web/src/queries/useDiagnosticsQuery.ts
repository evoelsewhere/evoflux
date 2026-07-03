import { useQuery } from '@tanstack/react-query'
import { getDiagnostics } from '@/api/client'
import { queryKeys } from './keys'

export function useDiagnosticsQuery() {
  return useQuery({
    queryKey: queryKeys.diagnostics(),
    queryFn: getDiagnostics,
    staleTime: 0,      // always re-fetch on mount
    gcTime: 60_000,
    retry: 1,
  })
}
