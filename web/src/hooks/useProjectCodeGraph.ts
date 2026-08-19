import { useEffect, useMemo, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getProjectCodeGraphStatus, reindexProjectCodeGraph } from '@/api/client'
import { queryKeys } from '@/queries/keys'

export function useProjectCodeGraph(projectId: string, enabled = true) {
  const queryClient = useQueryClient()
  const wasIndexing = useRef(false)
  const statusKey = queryKeys.projects.codeGraphStatus(projectId)

  const statusQuery = useQuery({
    queryKey: statusKey,
    queryFn: () => getProjectCodeGraphStatus(projectId),
    enabled: enabled && projectId.length > 0,
    staleTime: 2_000,
    refetchInterval: (query) =>
      query.state.data?.some((repo) => repo.indexing) ? 500 : false,
  })

  const reindexMutation = useMutation({
    mutationFn: (full: boolean) => reindexProjectCodeGraph(projectId, { full }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: statusKey })
    },
  })

  const repos = useMemo(() => statusQuery.data ?? [], [statusQuery.data])
  const indexing = repos.some((repo) => repo.indexing)

  useEffect(() => {
    if (wasIndexing.current && !indexing) {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.projects.codeGraphData(projectId),
      })
      void queryClient.invalidateQueries({
        queryKey: ['projects', 'detail', projectId, 'code-context-search'],
      })
    }
    wasIndexing.current = indexing
  }, [indexing, projectId, queryClient])

  const summary = useMemo(() => {
    const indexed = repos.filter((repo) => repo.indexed).length
    const failed = repos.filter((repo) => Boolean(repo.index_error)).length
    const files = repos.reduce((total, repo) => total + repo.files, 0)
    const symbols = repos.reduce((total, repo) => total + repo.nodes, 0)
    const relations = repos.reduce((total, repo) => total + repo.edges, 0)
    return {
      indexed,
      failed,
      files,
      symbols,
      relations,
      coverage: repos.length > 0 ? indexed / repos.length : 0,
    }
  }, [repos])

  return {
    repos,
    summary,
    statusQuery,
    reindex: (full = false) => reindexMutation.mutate(full),
    reindexMutation,
    isBusy: indexing || reindexMutation.isPending,
  }
}
