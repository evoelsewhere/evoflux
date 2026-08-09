import { useQuery, useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query'
import {
  getCodingWorkspaceTree,
  getProject,
  createProject,
  updateProject,
  deleteProject,
  addWorkspaceToProject,
  removeWorkspaceFromProject,
  updateWorkspaceInProject,
} from '@/api/client'
import type { CodingProject, ProjectCreateRequest, AddWorkspaceToProjectRequest } from '@/api/types'
import { queryKeys } from './keys'

export function useCodingOverviewQuery() {
  return useQuery({
    queryKey: queryKeys.codingOverview(),
    queryFn: getCodingWorkspaceTree,
    staleTime: 60_000,
  })
}

function refetchCodingOverview(queryClient: QueryClient) {
  return queryClient.refetchQueries({
    queryKey: queryKeys.codingOverview(),
    type: 'all',
  })
}

export function useProjectQuery(id: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.projects.detail(id ?? ''),
    queryFn: () => getProject(id!),
    enabled: !!id,
    staleTime: 60_000,
  })
}

export function useCreateProjectMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ProjectCreateRequest) => createProject(body),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.projects.all() }),
        refetchCodingOverview(queryClient),
      ])
    },
  })
}

export function useUpdateProjectMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: string
      body: Partial<{ name: string; description: string; settings: Record<string, unknown> }>
    }) => updateProject(id, body),
    onSuccess: async (updated: CodingProject) => {
      queryClient.setQueryData(queryKeys.projects.detail(updated.id), updated)
      await refetchCodingOverview(queryClient)
    },
  })
}

export function useDeleteProjectMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deleteProject(id),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.projects.all() }),
        refetchCodingOverview(queryClient),
      ])
    },
  })
}

export function useAddWorkspaceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      projectId,
      body,
    }: {
      projectId: string
      body: AddWorkspaceToProjectRequest
    }) => addWorkspaceToProject(projectId, body),
    onSuccess: async (_ws, { projectId }) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.projects.detail(projectId) }),
        refetchCodingOverview(queryClient),
      ])
    },
  })
}

export function useRemoveWorkspaceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      projectId,
      workspaceId,
    }: {
      projectId: string
      workspaceId: string
    }) => removeWorkspaceFromProject(projectId, workspaceId),
    onSuccess: async (_v, { projectId }) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.projects.detail(projectId) }),
        refetchCodingOverview(queryClient),
      ])
    },
  })
}

export function useUpdateWorkspaceInProjectMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      projectId,
      workspaceId,
      body,
    }: {
      projectId: string
      workspaceId: string
      body: Partial<{ display_name: string; sort_order: number }>
    }) => updateWorkspaceInProject(projectId, workspaceId, body),
    onSuccess: async (_ws, { projectId }) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.projects.detail(projectId) }),
        refetchCodingOverview(queryClient),
      ])
    },
  })
}
