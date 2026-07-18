/**
 * EvoFlux API client — AIM group: folder-layout detection, project
 * create/preview/join (setup wizard), and the read-only summary/units/runs
 * index that powers Overview and Runs & Reports.
 * See documents/plans/aim-mode-shell-ux-spec.md (v2.2).
 */

import { apiBaseUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'
import type {
  AimLayoutDetection,
  AimManifestPreview,
  AimMeta,
  AimProjectCreateRequest,
  AimProjectJoinRequest,
  AimProjectSummary,
  AimReindexResponse,
  AimRulebook,
  AimRunListItem,
  AimRunOut,
  AimUnitOut,
  CodingProject,
} from '../types'

export async function listAimProjects(): Promise<CodingProject[]> {
  const res = await fetch(`${apiBaseUrl()}/team/projects?kind=aim`)
  if (!res.ok) await parseDetailOrThrow(res, 'listAimProjects')
  return res.json()
}

export async function getAimMeta(): Promise<AimMeta> {
  const res = await fetch(`${apiBaseUrl()}/team/projects/aim/meta`)
  if (!res.ok) await parseDetailOrThrow(res, 'getAimMeta')
  return res.json()
}

export async function detectAimLayout(rootPath: string): Promise<AimLayoutDetection> {
  const params = new URLSearchParams({ root_path: rootPath })
  const res = await fetch(`${apiBaseUrl()}/team/projects/aim/detect?${params}`, {
    method: 'POST',
  })
  if (!res.ok) await parseDetailOrThrow(res, 'detectAimLayout')
  return res.json()
}

export async function previewAimManifest(kbPath: string): Promise<AimManifestPreview> {
  const params = new URLSearchParams({ kb_path: kbPath })
  const res = await fetch(`${apiBaseUrl()}/team/projects/aim/preview?${params}`, {
    method: 'POST',
  })
  if (!res.ok) await parseDetailOrThrow(res, 'previewAimManifest')
  return res.json()
}

export async function createAimProject(
  body: AimProjectCreateRequest,
): Promise<CodingProject> {
  const res = await fetch(`${apiBaseUrl()}/team/projects/aim`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'createAimProject')
  return res.json()
}

export async function joinAimProject(body: AimProjectJoinRequest): Promise<CodingProject> {
  const res = await fetch(`${apiBaseUrl()}/team/projects/aim/join`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'joinAimProject')
  return res.json()
}

export async function getAimProjectSummary(projectId: string): Promise<AimProjectSummary> {
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/aim/summary`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'getAimProjectSummary')
  return res.json()
}

export async function listAimUnits(
  projectId: string,
  options?: { phase?: string; wave?: number },
): Promise<AimUnitOut[]> {
  const params = new URLSearchParams()
  if (options?.phase) params.set('phase', options.phase)
  if (options?.wave !== undefined) params.set('wave', String(options.wave))
  const query = params.toString()
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/aim/units${query ? `?${query}` : ''}`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'listAimUnits')
  return res.json()
}

export async function listAimRuns(
  projectId: string,
  limit = 50,
): Promise<AimRunListItem[]> {
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/aim/runs?limit=${limit}`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'listAimRuns')
  return res.json()
}

export async function reindexAimProject(projectId: string): Promise<AimReindexResponse> {
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/aim/reindex`,
    { method: 'POST' },
  )
  if (!res.ok) await parseDetailOrThrow(res, 'reindexAimProject')
  return res.json()
}

export async function getAimRulebook(projectId: string): Promise<AimRulebook> {
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/aim/rulebook`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'getAimRulebook')
  return res.json()
}

export async function getAimRun(projectId: string, runId: string): Promise<AimRunOut> {
  const res = await fetch(
    `${apiBaseUrl()}/team/projects/${encodeURIComponent(projectId)}/aim/runs/${encodeURIComponent(runId)}`,
  )
  if (!res.ok) await parseDetailOrThrow(res, 'getAimRun')
  return res.json()
}
