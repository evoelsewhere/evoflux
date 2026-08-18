import { useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getCodeGraphStatus, reindexCodeGraph } from '@/api/client'
import type { ProjectRepoStatus } from '@/api/types'
import { queryKeys } from '@/queries/keys'

function repositoryName(workspace: string): string {
  return workspace.split(/[\\/]/).pop() || workspace
}

export function useWorkspaceCodeGraph(workspace: string, enabled = true) {
  const queryClient = useQueryClient()
  const statusKey = queryKeys.codeGraph.status(workspace)
  const statusQuery = useQuery({
    queryKey: statusKey,
    queryFn: () => getCodeGraphStatus(workspace),
    enabled: enabled && workspace.length > 0,
    staleTime: 2_000,
    refetchInterval: (query) => (query.state.data?.indexing ? 500 : false),
  })

  const reindexMutation = useMutation({
    mutationFn: (full: boolean) => reindexCodeGraph(workspace, { full }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.codeGraph.all(workspace) })
    },
  })

  const repo = useMemo<ProjectRepoStatus>(() => {
    const status = statusQuery.data
    return {
      workspace_id: workspace,
      path: workspace,
      name: repositoryName(workspace),
      indexed: status?.indexed ?? false,
      files: status?.files ?? 0,
      nodes: status?.nodes ?? 0,
      edges: status?.edges ?? 0,
      indexing: status?.indexing ?? false,
      index_phase: status?.index_phase ?? null,
      index_progress: status?.index_progress ?? null,
      index_message: status?.index_message ?? null,
      index_error: status?.index_error ?? null,
    }
  }, [statusQuery.data, workspace])

  const indexed = repo.indexed ? 1 : 0
  return {
    repos: [repo],
    summary: {
      indexed,
      failed: repo.index_error ? 1 : 0,
      files: repo.files,
      symbols: repo.nodes,
      relations: repo.edges,
      coverage: indexed,
    },
    statusQuery,
    reindex: (full = false) => reindexMutation.mutate(full),
    reindexMutation,
    isBusy: repo.indexing || reindexMutation.isPending,
  }
}
