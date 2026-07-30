import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createAimProject,
  deleteProject,
  detectAimLayout,
  joinAimProject,
  listAimProjects,
} from '@/api/client'
import type {
  AimProjectCreateRequest,
  AimProjectJoinRequest,
  CodingProject,
} from '@/api/types'
import { queryKeys } from './keys'

export function useAimProjectsQuery() {
  return useQuery({
    queryKey: queryKeys.projects.aimAll(),
    queryFn: listAimProjects,
    staleTime: 60_000,
  })
}

export function useDetectAimLayoutMutation() {
  return useMutation({
    mutationFn: (rootPath: string) => detectAimLayout(rootPath),
  })
}

export function useCreateAimProjectMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: AimProjectCreateRequest) => createAimProject(body),
    onSuccess: (created: CodingProject) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.aimAll() })
      queryClient.setQueryData(queryKeys.projects.detail(created.id), created)
    },
  })
}

export function useJoinAimProjectMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: AimProjectJoinRequest) => joinAimProject(body),
    onSuccess: (joined: CodingProject) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.aimAll() })
      queryClient.setQueryData(queryKeys.projects.detail(joined.id), joined)
    },
  })
}

export function useRemoveAimProjectMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deleteProject(id),
    onSuccess: (_result, id) => {
      queryClient.setQueryData<CodingProject[]>(
        queryKeys.projects.aimAll(),
        (projects) => projects?.filter((project) => project.id !== id),
      )
      queryClient.removeQueries({ queryKey: queryKeys.projects.detail(id) })
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.aimAll() })
    },
  })
}
