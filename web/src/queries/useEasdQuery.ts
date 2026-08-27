import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  acceptEasdPlanRevision,
  acceptEasdRevision,
  addEasdDeviation,
  addEasdEvidence,
  convergeEasdRun,
  createEasdRun,
  createEasdRevision,
  getEasdSetup,
  generateEasdScopeAndProof,
  getEasdRun,
  initializeEasdSetup,
  listEasdRuns,
  retryEasdPlanningInChat,
  retryEasdSpecAuthoringInChat,
  startEasdRunInChat,
  startEasdPlanningInChat,
  startEasdReviewInChat,
  startEasdSpecAuthoringInChat,
  startEasdVerificationInChat,
} from '@/api/client'
import type {
  EasdAppendableEvidenceKind,
  EasdAuthoringMetadata,
  EasdEvidenceResult,
  EasdGenerateRequest,
  EasdSpecificationInput,
} from '@/api/types'
import { queryKeys } from './keys'

export function useEasdSetupQuery(
  workspace: string,
  projectId?: string | null,
  enabled = true,
) {
  return useQuery({
    queryKey: queryKeys.easd.setup(workspace, projectId),
    queryFn: () => getEasdSetup(workspace, projectId),
    enabled: Boolean(workspace) && enabled,
  })
}

export function useInitializeEasdSetupMutation(
  workspace: string,
  projectId?: string | null,
) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { repositoryPaths?: string[]; dataDirectory?: string; overwrite?: boolean }) =>
      initializeEasdSetup({
        workspace,
        project_id: projectId,
        repository_paths: body.repositoryPaths,
        data_directory: body.dataDirectory,
        overwrite: body.overwrite,
      }),
    onSuccess: async (setup) => {
      client.setQueryData(queryKeys.easd.setup(workspace, projectId), setup)
      await client.invalidateQueries({ queryKey: queryKeys.easd.list(workspace, projectId) })
    },
  })
}

export function useEasdRunsQuery(
  workspace: string,
  projectId?: string | null,
  enabled = true,
) {
  return useQuery({
    queryKey: queryKeys.easd.list(workspace, projectId),
    queryFn: () => listEasdRuns(workspace, projectId),
    enabled: Boolean(workspace) && enabled,
  })
}

export function useGenerateEasdScopeAndProofMutation() {
  return useMutation({
    mutationFn: ({ request, signal }: { request: EasdGenerateRequest; signal?: AbortSignal }) =>
      generateEasdScopeAndProof(request, signal),
  })
}

export function useEasdRunQuery(runId: string | null, enabled = true) {
  return useQuery({
    queryKey: queryKeys.easd.detail(runId ?? ''),
    queryFn: () => getEasdRun(runId!),
    enabled: Boolean(runId) && enabled,
    refetchInterval: (query) => {
      const status = query.state.data?.run.status
      return ['authoring', 'planning', 'active', 'reviewing', 'verifying'].includes(status ?? '') ? 2_500 : false
    },
  })
}

export function useCreateEasdRunMutation(workspace: string, projectId?: string | null) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      sessionId?: string | null
      intent?: { title: string; problem: string; outcome?: string }
      specification?: EasdSpecificationInput
      authoring?: EasdAuthoringMetadata | null
    }) => createEasdRun({
      workspace,
      project_id: projectId,
      session_id: body.sessionId,
      intent: body.intent,
      specification: body.specification,
      authoring: body.authoring,
    }),
    onSuccess: async (detail) => {
      client.setQueryData(queryKeys.easd.detail(detail.run.id), detail)
      await client.invalidateQueries({ queryKey: queryKeys.easd.list(workspace, projectId) })
    },
  })
}

export function useCreateEasdRevisionMutation(runId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      specification: EasdSpecificationInput
      authoring?: EasdAuthoringMetadata | null
    }) => createEasdRevision(runId, body.specification, body.authoring),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.easd.runs() }),
  })
}

function useEasdAction(action: () => Promise<unknown>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: action,
    // Lifecycle changes alter both detail and every workspace/project list that
    // may contain this run. The shared prefix prevents a stale Board/Table/List
    // card after Accept, Start, or Converge.
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.easd.runs() }),
  })
}

export function useAcceptEasdRevisionMutation(runId: string, revisionId: string, hash: string) {
  return useEasdAction(() => acceptEasdRevision(runId, revisionId, hash))
}

export function useAcceptEasdPlanRevisionMutation(runId: string, revisionId: string, hash: string) {
  return useEasdAction(() => acceptEasdPlanRevision(runId, revisionId, hash))
}

export function useStartEasdRunInChatMutation(runId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: string) => startEasdRunInChat(runId, sessionId),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.easd.runs() }),
  })
}

export function useStartEasdSpecAuthoringMutation(runId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: string) => startEasdSpecAuthoringInChat(runId, sessionId),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.easd.runs() }),
  })
}

export function useRetryEasdSpecAuthoringMutation(runId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: string) => retryEasdSpecAuthoringInChat(runId, sessionId),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.easd.runs() }),
  })
}

function useStartEasdPhaseMutation(
  runId: string,
  action: (runId: string, sessionId: string) => Promise<unknown>,
) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: string) => action(runId, sessionId),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.easd.runs() }),
  })
}

export function useStartEasdPlanningMutation(runId: string) {
  return useStartEasdPhaseMutation(runId, startEasdPlanningInChat)
}

export function useRetryEasdPlanningMutation(runId: string) {
  return useStartEasdPhaseMutation(runId, retryEasdPlanningInChat)
}

export function useStartEasdReviewMutation(runId: string) {
  return useStartEasdPhaseMutation(runId, startEasdReviewInChat)
}

export function useStartEasdVerificationMutation(runId: string) {
  return useStartEasdPhaseMutation(runId, startEasdVerificationInChat)
}

export function useConvergeEasdRunMutation(runId: string) {
  return useEasdAction(() => convergeEasdRun(runId))
}

export function useAddEasdEvidenceMutation(runId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      spec_hash: string
      criterion_ids: string[]
      producer: string
      kind: EasdAppendableEvidenceKind
      result: EasdEvidenceResult
      summary: string
    }) => addEasdEvidence(runId, body),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.easd.runs() }),
  })
}

export function useAddEasdDeviationMutation(runId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { description: string; criterion_id?: string | null }) =>
      addEasdDeviation(runId, body),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.easd.runs() }),
  })
}
