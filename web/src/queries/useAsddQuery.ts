import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  approveAsddArtifact,
  archiveAsddChange,
  createAsddChange,
  deleteAsddChange,
  getAsddChange,
  getAsddSetup,
  getAsddSpec,
  initializeAsddSetup,
  listAsddChanges,
  markAsddChangeReady,
  setAsddAutopilot,
  startAsddAction,
} from '@/api/client'
import type { AsddApproveArtifact, AsddChangeDetail, AsddRisk } from '@/api/types'
import { queryKeys } from './keys'

/**
 * How often an open panel re-reads the catalogue.
 *
 * Agents write a change's files with the ordinary file tools, not through this
 * API, so no server event exists to push. Polling is what makes the panel
 * reflect a proposal an agent just wrote in the chat beside it. Only while the
 * panel is on screen: the queries are disabled when it is not.
 */
const CATALOGUE_POLL_MS = 4_000

export function useAsddSetupQuery(
  workspace: string,
  projectId?: string | null,
  enabled = true,
) {
  return useQuery({
    queryKey: queryKeys.asdd.setup(workspace, projectId),
    queryFn: () => getAsddSetup(workspace, projectId),
    enabled: Boolean(workspace) && enabled,
  })
}

export function useInitializeAsddSetupMutation(
  workspace: string,
  projectId?: string | null,
) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      repositoryPaths?: string[]
      dataDirectory?: string
      overwrite?: boolean
    }) =>
      initializeAsddSetup({
        workspace,
        project_id: projectId,
        repository_paths: body.repositoryPaths,
        data_directory: body.dataDirectory,
        overwrite: body.overwrite,
      }),
    onSuccess: async (setup) => {
      client.setQueryData(queryKeys.asdd.setup(workspace, projectId), setup)
      await client.invalidateQueries({
        queryKey: queryKeys.asdd.changes(workspace, projectId),
      })
    },
  })
}

export function useAsddChangesQuery(
  workspace: string,
  projectId?: string | null,
  enabled = true,
) {
  return useQuery({
    queryKey: queryKeys.asdd.changes(workspace, projectId),
    queryFn: () => listAsddChanges(workspace, projectId),
    enabled: Boolean(workspace) && enabled,
    refetchInterval: CATALOGUE_POLL_MS,
    refetchOnWindowFocus: true,
  })
}

export function useAsddChangeQuery(
  workspace: string,
  changeId: string | null,
  enabled = true,
) {
  return useQuery({
    queryKey: queryKeys.asdd.detail(workspace, changeId ?? ''),
    queryFn: () => getAsddChange(workspace, changeId as string),
    enabled: Boolean(workspace) && Boolean(changeId) && enabled,
    refetchInterval: CATALOGUE_POLL_MS,
    refetchOnWindowFocus: true,
  })
}

export function useAsddSpecQuery(
  workspace: string,
  capability: string | null,
  enabled = true,
) {
  return useQuery({
    queryKey: queryKeys.asdd.spec(workspace, capability ?? ''),
    queryFn: () => getAsddSpec(workspace, capability as string),
    enabled: Boolean(workspace) && Boolean(capability) && enabled,
  })
}

/**
 * Seed the detail cache from a mutation result and invalidate the list.
 *
 * Writing the fresh detail straight into the cache matters here: every ASDD
 * mutation returns the change re-read from disk, so the panel can show the new
 * state without a second request that might land mid-write.
 */
function useApplyDetail(workspace: string, projectId?: string | null) {
  const client = useQueryClient()
  return async (detail: AsddChangeDetail) => {
    client.setQueryData(
      queryKeys.asdd.detail(workspace, detail.change.change_id),
      detail,
    )
    await client.invalidateQueries({
      queryKey: queryKeys.asdd.changes(workspace, projectId),
    })
  }
}

export function useCreateAsddChangeMutation(
  workspace: string,
  projectId?: string | null,
) {
  const apply = useApplyDetail(workspace, projectId)
  return useMutation({
    mutationFn: (body: {
      title: string
      problem?: string
      outcome?: string
      changeId?: string | null
      risk?: AsddRisk
      capabilities?: string[]
    }) =>
      createAsddChange({
        workspace,
        title: body.title,
        problem: body.problem,
        outcome: body.outcome,
        change_id: body.changeId,
        risk: body.risk,
        capabilities: body.capabilities,
      }),
    onSuccess: apply,
  })
}

export function useApproveAsddArtifactMutation(
  workspace: string,
  changeId: string,
  projectId?: string | null,
) {
  const apply = useApplyDetail(workspace, projectId)
  return useMutation({
    mutationFn: (body: { artifact: AsddApproveArtifact; note?: string | null }) =>
      approveAsddArtifact(workspace, changeId, body.artifact, body.note),
    onSuccess: apply,
  })
}

export function useStartAsddActionMutation(workspace: string, changeId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (action: string) => startAsddAction(workspace, changeId, action),
    onSuccess: async () => {
      await client.invalidateQueries({
        queryKey: queryKeys.asdd.detail(workspace, changeId),
      })
    },
  })
}

export function useMarkAsddChangeReadyMutation(
  workspace: string,
  changeId: string,
  projectId?: string | null,
) {
  const apply = useApplyDetail(workspace, projectId)
  return useMutation({
    mutationFn: () => markAsddChangeReady(workspace, changeId),
    onSuccess: apply,
  })
}

export function useSetAsddAutopilotMutation(
  workspace: string,
  changeId: string,
  projectId?: string | null,
) {
  const apply = useApplyDetail(workspace, projectId)
  return useMutation({
    mutationFn: (enabled: boolean) => setAsddAutopilot(workspace, changeId, enabled),
    onSuccess: apply,
  })
}

export function useArchiveAsddChangeMutation(
  workspace: string,
  changeId: string,
  projectId?: string | null,
) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => archiveAsddChange(workspace, changeId),
    onSuccess: async () => {
      client.removeQueries({ queryKey: queryKeys.asdd.detail(workspace, changeId) })
      await client.invalidateQueries({
        queryKey: queryKeys.asdd.changes(workspace, projectId),
      })
    },
  })
}

export function useDeleteAsddChangeMutation(
  workspace: string,
  projectId?: string | null,
) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (changeId: string) => deleteAsddChange(workspace, changeId),
    onSuccess: async (_result, changeId) => {
      client.removeQueries({ queryKey: queryKeys.asdd.detail(workspace, changeId) })
      await client.invalidateQueries({
        queryKey: queryKeys.asdd.changes(workspace, projectId),
      })
    },
  })
}
