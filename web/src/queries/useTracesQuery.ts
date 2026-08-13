import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { listTraces, getTraceDetail } from '@/api/client'
import { queryKeys } from './keys'

/** Paginated list of ``agent_run`` spans (one row per turn). */
export function useTracesQuery(days: number, limit = 50, offset = 0) {
  return useQuery({
    queryKey: queryKeys.observability.traces(days, limit, offset),
    queryFn: () => listTraces(days, limit, offset),
    staleTime: 10_000,
    refetchInterval: 30_000,
  })
}

/** Scroll-paginated list of ``agent_run`` spans. */
export function useInfiniteTracesQuery(days: number, limit = 25, enabled = true) {
  return useInfiniteQuery({
    queryKey: queryKeys.observability.infiniteTraces(days, limit),
    initialPageParam: 0,
    queryFn: ({ pageParam }) => listTraces(days, limit, pageParam),
    enabled,
    getNextPageParam: (lastPage) => (
      lastPage.has_next ? lastPage.offset + lastPage.limit : undefined
    ),
    staleTime: 30_000,
    refetchInterval: enabled ? 30_000 : false,
  })
}

/** Full span tree for one trace.  ``null`` when the trace has expired. */
export function useTraceDetailQuery(traceId: string | null) {
  return useQuery({
    queryKey: queryKeys.observability.trace(traceId ?? ''),
    queryFn: () => getTraceDetail(traceId!),
    // Only fetch when a trace is selected.
    enabled: traceId !== null && traceId !== '',
    // Historical data — never goes stale inside a session.
    staleTime: Infinity,
  })
}
