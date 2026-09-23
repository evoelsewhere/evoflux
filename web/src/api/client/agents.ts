/**
 * EvoFlux API client — config group: /agents, /skills, /commands, /snippets.
 */

import { apiBaseUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'
import { stripExtendedPathPrefix } from '@/lib/workspace-path-utils'
import type {
  AgentListResponse,
  AgentDetail,
  AgentDeleteResponse,
  AgentBulkModelResponse,
  RegistryResponse,
  SkillListResponse,
  SkillDetail,
  SkillBundleFileWrite,
  SkillDeleteResponse,
  CommandListResponse,
  CommandRenderResponse,
  SnippetListResponse,
  SnippetRenderResponse,
} from '../types'

/**
 * Discovery scope shared by the skill catalog and the agent registry.
 * Project skills are discovered from these authorized workspace roots;
 * Skills have no mode scope.
 */
export interface SkillDiscoveryScope {
  /** Authorized workspace roots, in discovery-precedence order. */
  workspaces?: readonly string[] | null
}

/** Trimmed, de-duplicated workspace roots in their original order. */
export function normalizeSkillWorkspaces(scope?: SkillDiscoveryScope): string[] {
  const seen = new Set<string>()
  const workspaces: string[] = []
  for (const rawWorkspace of scope?.workspaces ?? []) {
    const workspace = rawWorkspace.trim()
    if (!workspace || seen.has(workspace)) continue
    seen.add(workspace)
    workspaces.push(workspace)
  }
  return workspaces
}

function skillDiscoveryQuery(scope?: SkillDiscoveryScope): string {
  const params = new URLSearchParams()
  for (const workspace of normalizeSkillWorkspaces(scope)) {
    params.append('workspace', stripExtendedPathPrefix(workspace))
  }
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

export async function updateAgentRuntimeModel(
  name: string,
  model: string | null,
): Promise<AgentDetail> {
  const res = await fetch(
    `${apiBaseUrl()}/agents/runtime-model/${encodeURIComponent(name)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model }),
    },
  )
  if (!res.ok) {
    await parseDetailOrThrow(res, `PATCH /agents/runtime-model/${name}`)
  }
  return res.json()
}

export async function updateAgentRuntimeSettings(
  name: string,
  body: {
    model: string | null
    extra_tools: string[]
    extra_skills: string[]
    extra_mcp: string[]
  },
): Promise<AgentDetail> {
  const res = await fetch(
    `${apiBaseUrl()}/agents/runtime-settings/${encodeURIComponent(name)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
  if (!res.ok) {
    await parseDetailOrThrow(res, `PATCH /agents/runtime-settings/${name}`)
  }
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

/** Create a Skill in the user skills directory. */
export async function createSkill(
  name: string,
  content: string,
  files: SkillBundleFileWrite[] = [],
  scope?: SkillDiscoveryScope,
): Promise<SkillDetail> {
  const res = await fetch(`${apiBaseUrl()}/skills${skillDiscoveryQuery(scope)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, content, files }),
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
    body: JSON.stringify({ content, files, deleted_files: deletedFiles }),
  })
  if (!res.ok) await parseDetailOrThrow(res, `PUT /skills/${name}`)
  return res.json()
}

/** Turn a Skill on or off. Works for every Skill, including built-in and plugin ones. */
export async function setSkillEnabled(
  name: string,
  enabled: boolean,
  scope?: SkillDiscoveryScope,
): Promise<SkillDetail> {
  const res = await fetch(
    `${apiBaseUrl()}/skills/${encodeURIComponent(name)}${skillDiscoveryQuery(scope)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    },
  )
  if (!res.ok) await parseDetailOrThrow(res, `PATCH /skills/${name}`)
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
  if (workspace) params.set('workspace', stripExtendedPathPrefix(workspace))
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
  if (workspace) params.set('workspace', stripExtendedPathPrefix(workspace))
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
  const params = new URLSearchParams({ workspace: stripExtendedPathPrefix(workspace) })
  const res = await fetch(`${apiBaseUrl()}/snippets?${params.toString()}`)
  if (!res.ok) await parseDetailOrThrow(res, 'listSnippets')
  return res.json()
}

export async function renderSnippet(name: string, workspace: string): Promise<SnippetRenderResponse> {
  const encoded = name.split('/').map(encodeURIComponent).join('/')
  const params = new URLSearchParams({ workspace: stripExtendedPathPrefix(workspace) })
  const res = await fetch(`${apiBaseUrl()}/snippets/${encoded}/render?${params.toString()}`, {
    method: 'POST',
  })
  if (!res.ok) await parseDetailOrThrow(res, `POST /snippets/${name}/render`)
  return res.json()
}
