import { useQuery } from '@tanstack/react-query'
import { getObservabilitySummary } from '@/api/client'
import { queryKeys } from './keys'

export function useObservabilitySummaryQuery(days: number) {
  return useQuery({
    queryKey: queryKeys.observability.summary(days),
    queryFn: () => getObservabilitySummary(days),
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}
