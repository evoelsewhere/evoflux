import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  createGitServerConnection,
  createCodeReview,
  deleteGitServerConnection,
  getCodeReview,
  getCodeReviews,
  getGitServerConnections,
  mutateCodeReview,
  testGitServerConnection,
  updateGitServerConnection,
  type CodeReviewScope,
} from '@/api/client'
import type {
  CodeReviewActionInput,
  CodeReviewCreateInput,
  GitServerConnectionInput,
} from '@/api/types'
import { queryKeys } from './keys'

export function useCodeReviewsQuery(
  enabled = true,
  scope: CodeReviewScope = {},
) {
  const scopeKey = scope.projectId
    ? `project:${scope.projectId}`
    : scope.workspace
      ? `workspace:${scope.workspace}`
      : 'all'
  const stateKey = scope.state ?? 'open'
  return useQuery({
    queryKey: queryKeys.git.reviews(`${scopeKey}:${stateKey}`),
    queryFn: () => getCodeReviews(scope),
    enabled,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  })
}

export function useCodeReviewQuery(
  workspaceId: string | null,
  number: number | null,
  enabled = true,
) {
  return useQuery({
    queryKey: queryKeys.git.reviews(
      workspaceId && number ? `detail:${workspaceId}:${number}` : 'detail:none',
    ),
    queryFn: () => getCodeReview(workspaceId!, number!),
    enabled: enabled && Boolean(workspaceId && number),
    staleTime: 15_000,
  })
}

export function useCodeReviewActionMutation(
  workspaceId: string,
  number: number,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CodeReviewActionInput) =>
      mutateCodeReview(workspaceId, number, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.git.reviews() })
    },
  })
}

export function useCreateCodeReviewMutation(workspaceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CodeReviewCreateInput) =>
      createCodeReview(workspaceId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.git.reviews() })
    },
  })
}

export function useGitServerConnectionsQuery(enabled = true) {
  return useQuery({
    queryKey: queryKeys.git.connections(),
    queryFn: getGitServerConnections,
    enabled,
    staleTime: 30_000,
  })
}

export function useSaveGitServerConnectionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id?: string
      body: GitServerConnectionInput
    }) =>
      id
        ? updateGitServerConnection(id, body)
        : createGitServerConnection(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.git.connections(),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.git.reviews(),
      })
    },
  })
}

export function useDeleteGitServerConnectionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteGitServerConnection,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.git.connections(),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.git.reviews(),
      })
    },
  })
}

export function useTestGitServerConnectionMutation() {
  return useMutation({
    mutationFn: testGitServerConnection,
  })
}
