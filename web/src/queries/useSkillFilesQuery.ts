/** TanStack Query hooks for the skill CRUD API (``/api/skills``). */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  listSkillFiles,
  getSkill,
  createSkill,
  updateSkill,
  setSkillEnabled,
  deleteSkill,
  normalizeSkillWorkspaces,
} from '@/api/client'
import type { SkillDiscoveryScope } from '@/api/client'
import type { SkillBundleFileWrite } from '@/api/types'
import { queryKeys } from './keys'

/** Normalized scope, or ``undefined`` for the unscoped (global) catalog. */
function resolveScope(scope?: SkillDiscoveryScope): { workspaces: string[] } | undefined {
  return scope ? { workspaces: normalizeSkillWorkspaces(scope) } : undefined
}

function detailKey(name: string, resolved: { workspaces: string[] } | undefined) {
  return resolved
    ? queryKeys.skillFiles.detail(name, resolved.workspaces)
    : queryKeys.skillFiles.detail(name)
}

export function useSkillFilesQuery(scope?: SkillDiscoveryScope) {
  const resolved = resolveScope(scope)
  return useQuery({
    queryKey: resolved
      ? queryKeys.skillFiles.list(resolved.workspaces)
      : queryKeys.skillFiles.list(),
    queryFn: () => listSkillFiles(resolved),
    staleTime: 10_000,
  })
}

export function useSkillFileQuery(
  name: string | null | undefined,
  scope?: SkillDiscoveryScope,
) {
  const resolved = resolveScope(scope)
  return useQuery({
    queryKey: detailKey(name ?? '', resolved),
    queryFn: () => getSkill(name as string, resolved),
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

export function useCreateSkillMutation(scope?: SkillDiscoveryScope) {
  const client = useQueryClient()
  const resolved = resolveScope(scope)
  return useMutation({
    mutationFn: ({
      name,
      content,
      files = [],
    }: {
      name: string
      content: string
      files?: SkillBundleFileWrite[]
    }) => createSkill(name, content, files, resolved),
    onSuccess: () => invalidateAll(client),
  })
}

export function useUpdateSkillMutation(scope?: SkillDiscoveryScope) {
  const client = useQueryClient()
  const resolved = resolveScope(scope)
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
    }) => updateSkill(name, content, files, deletedFiles, resolved),
    onSuccess: (_data, { name }) => {
      invalidateAll(client)
      client.invalidateQueries({ queryKey: detailKey(name, resolved) })
    },
  })
}

/** Turn a Skill on or off (``PATCH /api/skills/{name}``). */
export function useSetSkillEnabledMutation(scope?: SkillDiscoveryScope) {
  const client = useQueryClient()
  const resolved = resolveScope(scope)
  return useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) =>
      setSkillEnabled(name, enabled, resolved),
    onSuccess: (data, { name }) => {
      client.setQueryData(detailKey(name, resolved), data)
      invalidateAll(client)
    },
  })
}

export function useDeleteSkillMutation(scope?: SkillDiscoveryScope) {
  const client = useQueryClient()
  const resolved = resolveScope(scope)
  return useMutation({
    mutationFn: (name: string) => deleteSkill(name, resolved),
    onSuccess: () => invalidateAll(client),
  })
}
