/** Evo Agent Specs (EASD) API client. */

import { apiBaseUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'
import type {
  EasdAppendableEvidenceKind,
  EasdAuthoringMetadata,
  EasdConvergenceReason,
  EasdDeviation,
  EasdEvidence,
  EasdEvidenceResult,
  EasdGenerateRequest,
  EasdGenerateResponse,
  EasdPlanRevision,
  EasdRun,
  EasdRunDetail,
  EasdSetupResponse,
  EasdSpecRevision,
  EasdSpecificationInput,
} from '../types'

export class EasdConvergenceApiError extends Error {
  reasons: EasdConvergenceReason[]

  constructor(reasons: EasdConvergenceReason[]) {
    super('EASD convergence gates are not satisfied.')
    this.name = 'EasdConvergenceApiError'
    this.reasons = reasons
  }
}

async function easdResponse<T>(response: Response, label: string): Promise<T> {
  if (response.ok) return response.json()
  if (response.status === 409) {
    try {
      const body = await response.clone().json()
      if (
        body?.detail?.code === 'easd_not_converged'
        && Array.isArray(body.detail.reasons)
      ) {
        throw new EasdConvergenceApiError(body.detail.reasons)
      }
    } catch (error) {
      if (error instanceof EasdConvergenceApiError) throw error
    }
  }
  return parseDetailOrThrow(response, label)
}

export async function listEasdRuns(
  workspace: string,
  projectId?: string | null,
): Promise<{ runs: EasdRun[] }> {
  const params = new URLSearchParams()
  if (projectId) params.set('project_id', projectId)
  else params.set('workspace', workspace)
  const response = await fetch(`${apiBaseUrl()}/easd/runs?${params}`)
  return easdResponse(response, 'listEasdRuns')
}

export async function getEasdSetup(
  workspace: string,
  projectId?: string | null,
): Promise<EasdSetupResponse> {
  const params = new URLSearchParams({ workspace })
  if (projectId) params.set('project_id', projectId)
  const response = await fetch(`${apiBaseUrl()}/easd/setup?${params}`)
  return easdResponse(response, 'getEasdSetup')
}

export async function generateEasdScopeAndProof(
  body: EasdGenerateRequest,
  signal?: AbortSignal,
): Promise<EasdGenerateResponse> {
  const response = await fetch(`${apiBaseUrl()}/easd/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  return easdResponse(response, 'generateEasdScopeAndProof')
}

export async function initializeEasdSetup(body: {
  workspace: string
  project_id?: string | null
  repository_paths?: string[] | null
  data_directory?: string | null
  overwrite?: boolean
}): Promise<EasdSetupResponse> {
  const response = await fetch(`${apiBaseUrl()}/easd/setup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return easdResponse(response, 'initializeEasdSetup')
}

export async function getEasdRun(runId: string): Promise<EasdRunDetail> {
  const response = await fetch(`${apiBaseUrl()}/easd/runs/${encodeURIComponent(runId)}`)
  return easdResponse(response, 'getEasdRun')
}

export async function createEasdRun(body: {
  workspace: string
  project_id?: string | null
  session_id?: string | null
  intent?: { title: string; problem: string; outcome?: string }
  specification?: EasdSpecificationInput
  authoring?: EasdAuthoringMetadata | null
}): Promise<EasdRunDetail> {
  const response = await fetch(`${apiBaseUrl()}/easd/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return easdResponse(response, 'createEasdRun')
}

export async function createEasdRevision(
  runId: string,
  specification: EasdSpecificationInput,
  authoring?: EasdAuthoringMetadata | null,
): Promise<EasdSpecRevision> {
  const response = await fetch(`${apiBaseUrl()}/easd/runs/${encodeURIComponent(runId)}/revisions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ specification, authoring }),
  })
  return easdResponse(response, 'createEasdRevision')
}

export async function acceptEasdRevision(
  runId: string,
  revisionId: string,
  expectedHash: string,
): Promise<EasdSpecRevision> {
  const response = await fetch(
    `${apiBaseUrl()}/easd/runs/${encodeURIComponent(runId)}/revisions/${encodeURIComponent(revisionId)}/accept`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_hash: expectedHash }),
    },
  )
  return easdResponse(response, 'acceptEasdRevision')
}

export async function acceptEasdPlanRevision(
  runId: string,
  revisionId: string,
  expectedHash: string,
): Promise<EasdPlanRevision> {
  const response = await fetch(
    `${apiBaseUrl()}/easd/runs/${encodeURIComponent(runId)}/plans/${encodeURIComponent(revisionId)}/accept`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_hash: expectedHash }),
    },
  )
  return easdResponse(response, 'acceptEasdPlanRevision')
}

export async function startEasdRunInChat(
  runId: string,
  sessionId: string,
): Promise<EasdRun> {
  const response = await fetch(`${apiBaseUrl()}/easd/runs/${encodeURIComponent(runId)}/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  })
  return easdResponse(response, 'startEasdRunInChat')
}

export async function startEasdSpecAuthoringInChat(
  runId: string,
  sessionId: string,
): Promise<EasdRun> {
  const response = await fetch(
    `${apiBaseUrl()}/easd/runs/${encodeURIComponent(runId)}/authoring/start`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    },
  )
  return easdResponse(response, 'startEasdSpecAuthoringInChat')
}

async function startEasdPhaseInChat(
  runId: string,
  sessionId: string,
  phase: 'planning' | 'review' | 'verification',
): Promise<EasdRun> {
  const response = await fetch(
    `${apiBaseUrl()}/easd/runs/${encodeURIComponent(runId)}/${phase}/start`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    },
  )
  return easdResponse(response, `startEasd${phase}InChat`)
}

export function startEasdPlanningInChat(runId: string, sessionId: string): Promise<EasdRun> {
  return startEasdPhaseInChat(runId, sessionId, 'planning')
}

export function startEasdReviewInChat(runId: string, sessionId: string): Promise<EasdRun> {
  return startEasdPhaseInChat(runId, sessionId, 'review')
}

export function startEasdVerificationInChat(runId: string, sessionId: string): Promise<EasdRun> {
  return startEasdPhaseInChat(runId, sessionId, 'verification')
}

export async function addEasdEvidence(
  runId: string,
  body: {
    spec_hash: string
    criterion_ids: string[]
    producer: string
    kind: EasdAppendableEvidenceKind
    result: EasdEvidenceResult
    summary: string
    delegation_task_id?: string | null
    revision?: string | null
    artifact_hash?: string | null
    payload?: Record<string, unknown>
    source_key?: string | null
  },
): Promise<EasdEvidence> {
  const response = await fetch(`${apiBaseUrl()}/easd/runs/${encodeURIComponent(runId)}/evidence`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return easdResponse(response, 'addEasdEvidence')
}

export async function addEasdDeviation(
  runId: string,
  body: {
    description: string
    blocking?: boolean
    criterion_id?: string | null
    delegation_task_id?: string | null
    proposed_change?: Record<string, unknown>
  },
): Promise<EasdDeviation> {
  const response = await fetch(`${apiBaseUrl()}/easd/runs/${encodeURIComponent(runId)}/deviations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return easdResponse(response, 'addEasdDeviation')
}

export async function convergeEasdRun(runId: string): Promise<{ report: Record<string, unknown> }> {
  const response = await fetch(`${apiBaseUrl()}/easd/runs/${encodeURIComponent(runId)}/converge`, {
    method: 'POST',
  })
  return easdResponse(response, 'convergeEasdRun')
}
