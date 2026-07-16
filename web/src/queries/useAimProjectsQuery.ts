import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createAimProject,
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
    staleTime: 10_000,
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
