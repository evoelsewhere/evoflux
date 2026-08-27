/**
 * TanStack Query hooks for the agent file CRUD API.
 *
 * On mutation success, invalidates both the agent file cache (settings UI)
 * and the live /team/agents cache so the team chat header refreshes its
 * badges after a reload.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  listAgents,
  getAgent,
  createAgent,
  updateAgent,
  deleteAgent,
  getRegistry,
  bulkUpdateAgentModel,
  updateAgentRuntimeModel,
  updateAgentRuntimeSettings,
} from '@/api/client'
import type { SkillDiscoveryScope } from '@/api/client'
import { queryKeys } from './keys'

export function useAgentFilesQuery() {
  return useQuery({
    queryKey: queryKeys.agentFiles.list(),
    queryFn: listAgents,
    staleTime: 10_000,
  })
}

export function useAgentFileQuery(name: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.agentFiles.detail(name ?? ''),
    queryFn: () => getAgent(name as string),
    enabled: !!name,
  })
}

export function useRegistryQuery(scope?: SkillDiscoveryScope) {
  const workspaces = [...new Set(
    (scope?.workspaces ?? []).map((workspace) => workspace.trim()).filter(Boolean),
  )]
  const mode = scope?.mode ?? null
  return useQuery({
    queryKey: scope
      ? queryKeys.agentFiles.registry(workspaces, mode)
      : queryKeys.agentFiles.registry(),
    queryFn: () => getRegistry(scope ? { workspaces, mode } : undefined),
    // Global model/tool metadata is process-stable. Workspace skill catalogs
    // are scoped and can change on disk, so do not retain them forever.
    staleTime: scope ? 10_000 : Infinity,
    gcTime: scope ? 5 * 60_000 : Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
}

function invalidateTeam(client: ReturnType<typeof useQueryClient>) {
  client.invalidateQueries({ queryKey: queryKeys.agentFiles.all() })
  client.invalidateQueries({ queryKey: queryKeys.agentFiles.registry() })
  client.invalidateQueries({ queryKey: queryKeys.agents() })
  client.invalidateQueries({ queryKey: queryKeys.team.status() })
  client.invalidateQueries({ queryKey: ['team', 'leads'] })
}

export function useCreateAgentMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ name, content }: { name: string; content: string }) =>
      createAgent(name, content),
    onSuccess: () => invalidateTeam(client),
  })
}

export function useUpdateAgentMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ name, content }: { name: string; content: string }) =>
      updateAgent(name, content),
    onSuccess: (_data, { name }) => {
      invalidateTeam(client)
      client.invalidateQueries({ queryKey: queryKeys.agentFiles.detail(name) })
    },
  })
}

export function useDeleteAgentMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => deleteAgent(name),
    onSuccess: () => invalidateTeam(client),
  })
}

export function useBulkUpdateAgentModelMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ names, model }: { names: string[]; model: string }) =>
      bulkUpdateAgentModel(names, model),
    onSuccess: () => invalidateTeam(client),
  })
}

export function useUpdateAgentRuntimeModelMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ name, model }: { name: string; model: string | null }) =>
      updateAgentRuntimeModel(name, model),
    onSuccess: (_data, { name }) => {
      invalidateTeam(client)
      client.invalidateQueries({ queryKey: queryKeys.agentFiles.detail(name) })
    },
  })
}

export function useUpdateAgentRuntimeSettingsMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      name,
      model,
      extraTools,
      extraSkills,
      extraMcp,
    }: {
      name: string
      model: string | null
      extraTools: string[]
      extraSkills: string[]
      extraMcp: string[]
    }) =>
      updateAgentRuntimeSettings(name, {
        model,
        extra_tools: extraTools,
        extra_skills: extraSkills,
        extra_mcp: extraMcp,
      }),
    onSuccess: (_data, { name }) => {
      invalidateTeam(client)
      client.invalidateQueries({ queryKey: queryKeys.agentFiles.detail(name) })
    },
  })
}
