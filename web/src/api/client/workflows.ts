/**
 * EvoFlux API client — Workflows group (plan v5 §8/§9.1): definition
 * CRUD + approval, run/stop, execution debug log.
 */

import { apiBaseUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'
import type {
  WorkflowDetail,
  WorkflowExecutionDetail,
  WorkflowExecutionListResponse,
  WorkflowListItem,
  WorkflowRunResult,
} from '../types'

function withWorkspace(base: string, workspace?: string | null): string {
  if (!workspace) return base
  const separator = base.includes('?') ? '&' : '?'
  return `${base}${separator}workspace=${encodeURIComponent(workspace)}`
}

export async function listWorkflows(
  workspace?: string | null,
): Promise<{ workflows: WorkflowListItem[] }> {
  const res = await fetch(withWorkspace(`${apiBaseUrl()}/workflows`, workspace))
  if (!res.ok) await parseDetailOrThrow(res, 'listWorkflows')
  return res.json()
}

export async function getWorkflow(
  name: string,
  workspace?: string | null,
): Promise<WorkflowDetail> {
  const res = await fetch(
    withWorkspace(`${apiBaseUrl()}/workflows/${encodeURIComponent(name)}`, workspace),
  )
  if (!res.ok) await parseDetailOrThrow(res, 'getWorkflow')
  return res.json()
}

export async function saveWorkflow(
  name: string,
  body: { raw_yaml?: string; graph?: Record<string, unknown> },
  workspace?: string | null,
): Promise<WorkflowDetail> {
  const res = await fetch(
    withWorkspace(`${apiBaseUrl()}/workflows/${encodeURIComponent(name)}`, workspace),
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'saveWorkflow')
  return res.json()
}

export async function deleteWorkflow(
  name: string,
  workspace?: string | null,
): Promise<void> {
  const res = await fetch(
    withWorkspace(`${apiBaseUrl()}/workflows/${encodeURIComponent(name)}`, workspace),
    { method: 'DELETE' },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'deleteWorkflow')
}

export async function approveWorkflow(
  name: string,
  hash: string,
  workspace?: string | null,
): Promise<void> {
  const res = await fetch(
    withWorkspace(
      `${apiBaseUrl()}/workflows/${encodeURIComponent(name)}/approve`,
      workspace,
    ),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hash }),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'approveWorkflow')
}

export async function runWorkflow(
  name: string,
  sessionId: string,
  inputs: Record<string, unknown>,
  workspace?: string | null,
  retryOfExecutionId?: string | null,
): Promise<WorkflowRunResult> {
  const res = await fetch(
    withWorkspace(`${apiBaseUrl()}/workflows/${encodeURIComponent(name)}/run`, workspace),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        inputs,
        retry_of_execution_id: retryOfExecutionId ?? null,
      }),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'runWorkflow')
  return res.json()
}

export async function stopExecution(executionId: string): Promise<void> {
  const res = await fetch(
    `${apiBaseUrl()}/workflows/executions/${encodeURIComponent(executionId)}/stop`,
    { method: 'POST' },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'stopExecution')
}

export async function getExecution(
  executionId: string,
): Promise<WorkflowExecutionDetail> {
  const res = await fetch(
    `${apiBaseUrl()}/workflows/executions/${encodeURIComponent(executionId)}`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'getExecution')
  return res.json()
}

/** Newest-first executions for a set of sessions — the AIM Pipelines run
 * table joins its per-run sessions with real workflow status in one call. */
export async function listWorkflowExecutions(
  sessionIds: string[],
): Promise<WorkflowExecutionListResponse> {
  if (sessionIds.length === 0) return { executions: [] }
  const params = new URLSearchParams({ session_ids: sessionIds.join(',') })
  const res = await fetch(`${apiBaseUrl()}/workflows/executions?${params}`)
  if (!res.ok) await parseDetailOrThrow(res, 'listWorkflowExecutions')
  return res.json()
}
