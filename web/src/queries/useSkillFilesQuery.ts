/** TanStack Query hooks for the skill CRUD API. */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  listSkillFiles,
  getSkill,
  createSkill,
  updateSkill,
  updateSkillSettings,
  resetSkillSettings,
  deleteSkill,
} from '@/api/client'
import type { SkillDiscoveryScope } from '@/api/client'
import type {
  SkillBundleFileWrite,
  SkillMode,
  SkillRuntimeSettingsUpdate,
} from '@/api/types'
import { queryKeys } from './keys'

function scopeParts(scope?: SkillDiscoveryScope) {
  const seen = new Set<string>()
  const workspaces: string[] = []
  for (const rawWorkspace of scope?.workspaces ?? []) {
    const workspace = rawWorkspace.trim()
    if (!workspace || seen.has(workspace)) continue
    seen.add(workspace)
    workspaces.push(workspace)
  }
  return {
    workspaces,
    mode: scope?.mode ?? null,
  }
}

export function useSkillFilesQuery(scope?: SkillDiscoveryScope) {
  const resolved = scopeParts(scope)
  return useQuery({
    queryKey: scope
      ? queryKeys.skillFiles.list(resolved.workspaces, resolved.mode)
      : queryKeys.skillFiles.list(),
    queryFn: () => listSkillFiles(scope ? resolved : undefined),
    staleTime: 10_000,
  })
}

export function useSkillFileQuery(
  name: string | null | undefined,
  scope?: SkillDiscoveryScope,
) {
  const resolved = scopeParts(scope)
  return useQuery({
    queryKey: scope
      ? queryKeys.skillFiles.detail(name ?? '', resolved.workspaces, resolved.mode)
      : queryKeys.skillFiles.detail(name ?? ''),
    queryFn: () => getSkill(name as string, scope ? resolved : undefined),
    enabled: !!name,
  })
}

function invalidateAll(client: ReturnType<typeof useQueryClient>) {
  client.invalidateQueries({ queryKey: queryKeys.skillFiles.all() })
  // Skills appear in the registry response and can affect agent reload.
  client.invalidateQueries({ queryKey: queryKeys.agentFiles.all() })
  client.invalidateQueries({ queryKey: queryKeys.agentFiles.registry() })
  client.invalidateQueries({ queryKey: queryKeys.agents() })
}

export function useCreateSkillMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      name,
      content,
      files = [],
      modes = ['work', 'coding'],
    }: {
      name: string
      content: string
      files?: SkillBundleFileWrite[]
      modes?: SkillMode[]
    }) => createSkill(name, content, files, modes),
    onSuccess: () => invalidateAll(client),
  })
}

export function useUpdateSkillMutation(scope?: SkillDiscoveryScope) {
  const client = useQueryClient()
  const resolved = scopeParts(scope)
  return useMutation({
    mutationFn: ({
      name,
      content,
      files = [],
      deletedFiles = [],
    }: {
      name: string
      content: string
      files?: SkillBundleFileWrite[]
      deletedFiles?: string[]
    }) => updateSkill(name, content, files, deletedFiles, scope ? resolved : undefined),
    onSuccess: (_data, { name }) => {
      invalidateAll(client)
      client.invalidateQueries({
        queryKey: scope
          ? queryKeys.skillFiles.detail(name, resolved.workspaces, resolved.mode)
          : queryKeys.skillFiles.detail(name),
      })
    },
  })
}

export function useUpdateSkillSettingsMutation(scope?: SkillDiscoveryScope) {
  const client = useQueryClient()
  const resolved = scopeParts(scope)
  return useMutation({
    mutationFn: ({
      name,
      settings,
    }: {
      name: string
      settings: SkillRuntimeSettingsUpdate
    }) => updateSkillSettings(name, settings, scope ? resolved : undefined),
    onSuccess: (_data, { name }) => {
      invalidateAll(client)
      client.invalidateQueries({
        queryKey: scope
          ? queryKeys.skillFiles.detail(name, resolved.workspaces, resolved.mode)
          : queryKeys.skillFiles.detail(name),
      })
    },
  })
}

export function useResetSkillSettingsMutation(scope?: SkillDiscoveryScope) {
  const client = useQueryClient()
  const resolved = scopeParts(scope)
  return useMutation({
    mutationFn: ({
      name,
      settingsId,
    }: {
      name: string
      settingsId: string
    }) => resetSkillSettings(name, settingsId, scope ? resolved : undefined),
    onSuccess: (_data, { name }) => {
      invalidateAll(client)
      client.invalidateQueries({
        queryKey: scope
          ? queryKeys.skillFiles.detail(name, resolved.workspaces, resolved.mode)
          : queryKeys.skillFiles.detail(name),
      })
    },
  })
}

export function useDeleteSkillMutation(scope?: SkillDiscoveryScope) {
  const client = useQueryClient()
  const resolved = scopeParts(scope)
  return useMutation({
    mutationFn: (name: string) => deleteSkill(name, scope ? resolved : undefined),
    onSuccess: () => invalidateAll(client),
  })
}
