import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  listProjects,
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

export function useProjectsQuery() {
  return useQuery({
    queryKey: queryKeys.projects.list(),
    queryFn: listProjects,
    staleTime: 10_000,
  })
}

export function useProjectQuery(id: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.projects.detail(id ?? ''),
    queryFn: () => getProject(id!),
    enabled: !!id,
    staleTime: 10_000,
  })
}

export function useCreateProjectMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ProjectCreateRequest) => createProject(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.all() })
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
    onSuccess: (updated: CodingProject) => {
      queryClient.setQueryData(queryKeys.projects.detail(updated.id), updated)
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.list() })
    },
  })
}

export function useDeleteProjectMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deleteProject(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.all() })
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
    onSuccess: (_ws, { projectId }) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.detail(projectId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.list() })
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
    onSuccess: (_v, { projectId }) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.detail(projectId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.list() })
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
    onSuccess: (_ws, { projectId }) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.detail(projectId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.list() })
    },
  })
}
