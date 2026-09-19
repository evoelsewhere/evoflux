/**
 * Agent Spec-Driven (ASDD) API client.
 *
 * Every call identifies a change by its slug and a repository by its workspace
 * path. There is no hash to echo back and no session to hold, so a panel can
 * always act on what it is currently showing.
 */

import { apiBaseUrl } from '../base-url'
import { ApiValidationError, parseDetailOrThrow } from './_shared'
import { stripExtendedPathPrefix } from '@/lib/workspace-path-utils'
import type {
  AsddApproveArtifact,
  AsddArchiveResult,
  AsddBlocker,
  AsddChange,
  AsddChangeActionResult,
  AsddChangeDetail,
  AsddChangeList,
  AsddSetupResponse,
  AsddSpec,
} from '../types'

/** A 409 whose detail names exactly what is standing in the way. */
export class AsddActionBlockedError extends ApiValidationError {
  blockers: AsddBlocker[]

  constructor(message: string, blockers: AsddBlocker[]) {
    super(409, message)
    this.name = 'AsddActionBlockedError'
    this.blockers = blockers
  }
}

async function asddResponse<T>(response: Response, label: string): Promise<T> {
  if (response.ok) return response.json()
  if (response.status === 409) {
    let detail: unknown
    try {
      detail = (await response.clone().json())?.detail
    } catch {
      detail = undefined
    }
    if (
      typeof detail === 'object'
      && detail !== null
      && (detail as { code?: string }).code === 'asdd_action_blocked'
    ) {
      const structured = detail as { message?: string, blockers?: AsddBlocker[] }
      throw new AsddActionBlockedError(
        structured.message ?? `${label} is blocked by the change's current state.`,
        structured.blockers ?? [],
      )
    }
    throw new ApiValidationError(
      409,
      typeof detail === 'string' ? detail : `${label} conflicts with what is on disk.`,
    )
  }
  return parseDetailOrThrow(response, label)
}

function json(body: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

export async function getAsddSetup(
  workspace: string,
  projectId?: string | null,
): Promise<AsddSetupResponse> {
  const params = new URLSearchParams({ workspace: stripExtendedPathPrefix(workspace) })
  if (projectId) params.set('project_id', projectId)
  const response = await fetch(`${apiBaseUrl()}/asdd/setup?${params}`)
  return asddResponse(response, 'getAsddSetup')
}

export async function initializeAsddSetup(body: {
  workspace: string
  project_id?: string | null
  repository_paths?: string[] | null
  data_directory?: string | null
  overwrite?: boolean
}): Promise<AsddSetupResponse> {
  const response = await fetch(`${apiBaseUrl()}/asdd/setup`, json(body))
  return asddResponse(response, 'initializeAsddSetup')
}

export async function listAsddChanges(
  workspace: string,
  projectId?: string | null,
): Promise<AsddChangeList> {
  const params = new URLSearchParams({ workspace: stripExtendedPathPrefix(workspace) })
  if (projectId) params.set('project_id', projectId)
  const response = await fetch(`${apiBaseUrl()}/asdd/changes?${params}`)
  return asddResponse(response, 'listAsddChanges')
}

export async function getAsddChange(
  workspace: string,
  changeId: string,
): Promise<AsddChangeDetail> {
  const params = new URLSearchParams({ workspace: stripExtendedPathPrefix(workspace) })
  const response = await fetch(
    `${apiBaseUrl()}/asdd/changes/${encodeURIComponent(changeId)}?${params}`,
  )
  return asddResponse(response, 'getAsddChange')
}

export async function createAsddChange(body: {
  workspace: string
  title: string
  /** Written into the proposal's `## Why`. */
  problem?: string
  /** Written into the proposal's `## What Changes`. */
  outcome?: string
  change_id?: string | null
  /** Omitted when the propose phase should choose the tier. */
  risk?: AsddChange['risk']
  capabilities?: string[]
}): Promise<AsddChangeDetail> {
  const response = await fetch(`${apiBaseUrl()}/asdd/changes`, json(body))
  return asddResponse(response, 'createAsddChange')
}

export async function deleteAsddChange(
  workspace: string,
  changeId: string,
): Promise<void> {
  const params = new URLSearchParams({ workspace: stripExtendedPathPrefix(workspace) })
  const response = await fetch(
    `${apiBaseUrl()}/asdd/changes/${encodeURIComponent(changeId)}?${params}`,
    { method: 'DELETE' },
  )
  if (response.ok) return
  await asddResponse(response, 'deleteAsddChange')
}

export async function approveAsddArtifact(
  workspace: string,
  changeId: string,
  artifact: AsddApproveArtifact,
  note?: string | null,
): Promise<AsddChangeDetail> {
  const response = await fetch(
    `${apiBaseUrl()}/asdd/changes/${encodeURIComponent(changeId)}/approve/${artifact}`,
    json({ workspace, note: note ?? null }),
  )
  return asddResponse(response, `approve ${artifact}`)
}

export async function startAsddAction(
  workspace: string,
  changeId: string,
  action: string,
): Promise<AsddChangeActionResult> {
  const response = await fetch(
    `${apiBaseUrl()}/asdd/changes/${encodeURIComponent(changeId)}/actions/${action}`,
    json({ workspace }),
  )
  return asddResponse(response, action)
}

export async function markAsddChangeReady(
  workspace: string,
  changeId: string,
): Promise<AsddChangeDetail> {
  const response = await fetch(
    `${apiBaseUrl()}/asdd/changes/${encodeURIComponent(changeId)}/ready`,
    json({ workspace }),
  )
  return asddResponse(response, 'markAsddChangeReady')
}

export async function setAsddAutopilot(
  workspace: string,
  changeId: string,
  enabled: boolean,
): Promise<AsddChangeDetail> {
  const response = await fetch(
    `${apiBaseUrl()}/asdd/changes/${encodeURIComponent(changeId)}/autopilot`,
    json({ workspace, enabled }),
  )
  return asddResponse(response, 'setAsddAutopilot')
}

export async function archiveAsddChange(
  workspace: string,
  changeId: string,
): Promise<AsddArchiveResult> {
  const response = await fetch(
    `${apiBaseUrl()}/asdd/changes/${encodeURIComponent(changeId)}/archive`,
    json({ workspace }),
  )
  return asddResponse(response, 'archiveAsddChange')
}

export async function recordAsddEvidence(body: {
  workspace: string
  evidence_id: string
  kind: 'machine' | 'review' | 'manual'
  result: 'passed' | 'failed' | 'inconclusive'
  summary: string
  requirement?: string | null
  body?: string
}, changeId: string): Promise<AsddChangeDetail> {
  const response = await fetch(
    `${apiBaseUrl()}/asdd/changes/${encodeURIComponent(changeId)}/evidence`,
    json(body),
  )
  return asddResponse(response, 'recordAsddEvidence')
}

export async function getAsddSpec(
  workspace: string,
  capability: string,
): Promise<AsddSpec> {
  const params = new URLSearchParams({ workspace: stripExtendedPathPrefix(workspace) })
  const response = await fetch(
    `${apiBaseUrl()}/asdd/specs/${encodeURIComponent(capability)}?${params}`,
  )
  return asddResponse(response, 'getAsddSpec')
}
