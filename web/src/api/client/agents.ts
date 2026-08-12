/**
 * EvoFlux API client — config group: /agents, /skills, /commands, /snippets.
 */

import { apiBaseUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'
import type {
  AgentListResponse,
  AgentDetail,
  AgentDeleteResponse,
  AgentBulkModelResponse,
  RegistryResponse,
  SkillListResponse,
  SkillDetail,
  SkillBundleFileWrite,
  SkillMode,
  SkillRuntimeSettingsUpdate,
  SkillDeleteResponse,
  CommandListResponse,
  CommandRenderResponse,
  SnippetListResponse,
  SnippetRenderResponse,
} from '../types'

/** Discovery scope shared by the skill catalog and the agent registry. */
export interface SkillDiscoveryScope {
  /** Authorized workspace roots, in discovery-precedence order. */
  workspaces?: readonly string[] | null
  mode?: SkillMode | null
}

function skillDiscoveryQuery(scope?: SkillDiscoveryScope): string {
  const params = new URLSearchParams()
  const seen = new Set<string>()
  for (const rawWorkspace of scope?.workspaces ?? []) {
    const workspace = rawWorkspace.trim()
    if (!workspace || seen.has(workspace)) continue
    seen.add(workspace)
    params.append('workspace', workspace)
  }
  if (scope?.mode) params.set('mode', scope.mode)
  const query = params.toString()
  return query ? `?${query}` : ''
}

export async function listAgents(): Promise<AgentListResponse> {
  const res = await fetch(`${apiBaseUrl()}/agents`)
  if (!res.ok) await parseDetailOrThrow(res, 'listAgents')
  return res.json()
}

export async function getAgent(name: string): Promise<AgentDetail> {
  const res = await fetch(`${apiBaseUrl()}/agents/${encodeURIComponent(name)}`)
  if (!res.ok) await parseDetailOrThrow(res, `GET /agents/${name}`)
  return res.json()
}

export async function createAgent(name: string, content: string): Promise<AgentDetail> {
  const res = await fetch(`${apiBaseUrl()}/agents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, content }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'POST /agents')
  return res.json()
}

export async function updateAgent(name: string, content: string): Promise<AgentDetail> {
  const res = await fetch(`${apiBaseUrl()}/agents/${encodeURIComponent(name)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, content }),
  })
  if (!res.ok) await parseDetailOrThrow(res, `PUT /agents/${name}`)
  return res.json()
}

export async function deleteAgent(name: string): Promise<AgentDeleteResponse> {
  const res = await fetch(`${apiBaseUrl()}/agents/${encodeURIComponent(name)}`, { method: 'DELETE' })
  if (!res.ok) await parseDetailOrThrow(res, `DELETE /agents/${name}`)
  return res.json()
}

export async function getRegistry(scope?: SkillDiscoveryScope): Promise<RegistryResponse> {
  const res = await fetch(`${apiBaseUrl()}/agents/registry${skillDiscoveryQuery(scope)}`)
  if (!res.ok) await parseDetailOrThrow(res, 'getRegistry')
  return res.json()
}

export async function bulkUpdateAgentModel(
  names: string[],
  model: string,
): Promise<AgentBulkModelResponse> {
  const res = await fetch(`${apiBaseUrl()}/agents/model`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ names, model }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'PATCH /agents/model')
  return res.json()
}

// ── /skills ──────────────────────────────────────────────────────────────────

export async function listSkillFiles(scope?: SkillDiscoveryScope): Promise<SkillListResponse> {
  const res = await fetch(`${apiBaseUrl()}/skills${skillDiscoveryQuery(scope)}`)
  if (!res.ok) await parseDetailOrThrow(res, 'listSkills')
  return res.json()
}

export async function getSkill(
  name: string,
  scope?: SkillDiscoveryScope,
): Promise<SkillDetail> {
  const res = await fetch(
    `${apiBaseUrl()}/skills/${encodeURIComponent(name)}${skillDiscoveryQuery(scope)}`,
  )
  if (!res.ok) await parseDetailOrThrow(res, `GET /skills/${name}`)
  return res.json()
}

export async function createSkill(
  name: string,
  content: string,
  files: SkillBundleFileWrite[] = [],
  modes: SkillMode[] = ['work', 'coding'],
): Promise<SkillDetail> {
  const res = await fetch(`${apiBaseUrl()}/skills`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, content, files, modes }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'POST /skills')
  return res.json()
}

export async function updateSkill(
  name: string,
  content: string,
  files: SkillBundleFileWrite[] = [],
  deletedFiles: string[] = [],
  scope?: SkillDiscoveryScope,
): Promise<SkillDetail> {
  const res = await fetch(`${apiBaseUrl()}/skills/${encodeURIComponent(name)}${skillDiscoveryQuery(scope)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, content, files, deleted_files: deletedFiles }),
  })
  if (!res.ok) await parseDetailOrThrow(res, `PUT /skills/${name}`)
  return res.json()
}

export async function updateSkillSettings(
  name: string,
  settings: SkillRuntimeSettingsUpdate,
  scope?: SkillDiscoveryScope,
): Promise<SkillDetail> {
  const res = await fetch(
    `${apiBaseUrl()}/skills/${encodeURIComponent(name)}${skillDiscoveryQuery(scope)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, `PATCH /skills/${name}`)
  return res.json()
}

export async function resetSkillSettings(
  name: string,
  settingsId: string,
  scope?: SkillDiscoveryScope,
): Promise<SkillDetail> {
  const scopedQuery = skillDiscoveryQuery(scope)
  const settingsQuery =
    `${scopedQuery}${scopedQuery ? '&' : '?'}settings_id=${encodeURIComponent(settingsId)}`
  const res = await fetch(
    `${apiBaseUrl()}/skills/${encodeURIComponent(name)}${settingsQuery}`,
    { method: 'DELETE' },
  )
  if (!res.ok) await parseDetailOrThrow(res, `DELETE /skills/${name} runtime settings`)
  return res.json()
}

export async function deleteSkill(
  name: string,
  scope?: SkillDiscoveryScope,
): Promise<SkillDeleteResponse> {
  const res = await fetch(
    `${apiBaseUrl()}/skills/${encodeURIComponent(name)}${skillDiscoveryQuery(scope)}`,
    { method: 'DELETE' },
  )
  if (!res.ok) await parseDetailOrThrow(res, `DELETE /skills/${name}`)
  return res.json()
}

// ── /commands ────────────────────────────────────────────────────────────────

export async function listCommands(workspace?: string | null): Promise<CommandListResponse> {
  const params = new URLSearchParams()
  if (workspace) params.set('workspace', workspace)
  const query = params.toString()
  const res = await fetch(`${apiBaseUrl()}/commands${query ? `?${query}` : ''}`)
  if (!res.ok) await parseDetailOrThrow(res, 'listCommands')
  return res.json()
}

export async function renderCommand(
  name: string,
  arguments_: string,
  workspace?: string | null,
): Promise<CommandRenderResponse> {
  // ``name`` may include slashes (nested folders); the segments are
  // already valid URL path chars, so we encode the whole id minus the
  // separator so e.g. ``git/commit`` survives intact.
  const encoded = name.split('/').map(encodeURIComponent).join('/')
  const params = new URLSearchParams()
  if (workspace) params.set('workspace', workspace)
  const query = params.toString()
  const res = await fetch(`${apiBaseUrl()}/commands/${encoded}/render${query ? `?${query}` : ''}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ arguments: arguments_ }),
  })
  if (!res.ok) await parseDetailOrThrow(res, `POST /commands/${name}/render`)
  return res.json()
}

// ── /snippets ───────────────────────────────────────────────────────────────

export async function listSnippets(workspace: string): Promise<SnippetListResponse> {
  const params = new URLSearchParams({ workspace })
  const res = await fetch(`${apiBaseUrl()}/snippets?${params.toString()}`)
  if (!res.ok) await parseDetailOrThrow(res, 'listSnippets')
  return res.json()
}

export async function renderSnippet(name: string, workspace: string): Promise<SnippetRenderResponse> {
  const encoded = name.split('/').map(encodeURIComponent).join('/')
  const params = new URLSearchParams({ workspace })
  const res = await fetch(`${apiBaseUrl()}/snippets/${encoded}/render?${params.toString()}`, {
    method: 'POST',
  })
  if (!res.ok) await parseDetailOrThrow(res, `POST /snippets/${name}/render`)
  return res.json()
}
