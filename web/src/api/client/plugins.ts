/** Portable Agent Plugins lifecycle API. */

import { apiBaseUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'
import type {
  PluginInspection,
  PluginCredentialState,
  PluginListResponse,
  PluginOperationResponse,
  PluginWorkspaceEntry,
  PluginWorkspaceFileResponse,
  PluginWorkspaceMutationResponse,
} from '../types'

export async function listPlugins(): Promise<PluginListResponse> {
  const response = await fetch(`${apiBaseUrl()}/plugins`)
  if (!response.ok) await parseDetailOrThrow(response, 'GET /plugins')
  return response.json()
}

export async function inspectPlugin(path: string): Promise<PluginInspection> {
  const response = await fetch(
    `${apiBaseUrl()}/plugins/inspect?path=${encodeURIComponent(path)}`,
  )
  if (!response.ok) await parseDetailOrThrow(response, 'GET /plugins/inspect')
  return response.json()
}

export async function importPlugin(
  path: string,
  mode: 'install' | 'link',
): Promise<PluginOperationResponse> {
  const response = await fetch(`${apiBaseUrl()}/plugins/install`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, mode, enabled: true }),
  })
  if (!response.ok) await parseDetailOrThrow(response, 'POST /plugins/install')
  return response.json()
}

export async function uploadPlugin(file: File): Promise<PluginOperationResponse> {
  const body = new FormData()
  body.append('archive', file)
  const response = await fetch(`${apiBaseUrl()}/plugins/upload`, {
    method: 'POST',
    body,
  })
  if (!response.ok) await parseDetailOrThrow(response, 'POST /plugins/upload')
  return response.json()
}

export async function updatePluginFromPath(
  id: string,
  path: string,
): Promise<PluginOperationResponse> {
  const response = await fetch(
    `${apiBaseUrl()}/plugins/${encodeURIComponent(id)}/update`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    },
  )
  if (!response.ok) await parseDetailOrThrow(response, 'POST /plugins/:id/update')
  return response.json()
}

export async function updatePluginFromUpload(
  id: string,
  file: File,
): Promise<PluginOperationResponse> {
  const body = new FormData()
  body.append('archive', file)
  const response = await fetch(
    `${apiBaseUrl()}/plugins/${encodeURIComponent(id)}/update-upload`,
    { method: 'POST', body },
  )
  if (!response.ok) {
    await parseDetailOrThrow(response, 'POST /plugins/:id/update-upload')
  }
  return response.json()
}

export async function setPluginEnabled(
  id: string,
  enabled: boolean,
): Promise<PluginOperationResponse> {
  const response = await fetch(
    `${apiBaseUrl()}/plugins/${encodeURIComponent(id)}/enabled`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    },
  )
  if (!response.ok) await parseDetailOrThrow(response, 'PATCH /plugins/:id/enabled')
  return response.json()
}

export async function uninstallPlugin(id: string): Promise<PluginOperationResponse> {
  const response = await fetch(`${apiBaseUrl()}/plugins/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
  if (!response.ok) await parseDetailOrThrow(response, 'DELETE /plugins/:id')
  return response.json()
}

export async function createPlugin(body: {
  destination: string
  name: string
  description: string
  version?: string
  author?: string
  license?: string
  skill_name?: string
  mcp_name?: string
}): Promise<{ path: string }> {
  const response = await fetch(`${apiBaseUrl()}/plugins/create`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) await parseDetailOrThrow(response, 'POST /plugins/create')
  return response.json()
}

export async function packPlugin(path: string): Promise<{ path: string }> {
  const response = await fetch(`${apiBaseUrl()}/plugins/pack`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
  if (!response.ok) await parseDetailOrThrow(response, 'POST /plugins/pack')
  return response.json()
}

export async function listPluginWorkspace(root: string): Promise<PluginWorkspaceEntry[]> {
  const response = await fetch(
    `${apiBaseUrl()}/plugins/workspace/tree?root=${encodeURIComponent(root)}`,
  )
  if (!response.ok) await parseDetailOrThrow(response, 'GET /plugins/workspace/tree')
  return response.json()
}

export async function readPluginWorkspaceFile(
  root: string,
  path: string,
): Promise<PluginWorkspaceFileResponse> {
  const params = new URLSearchParams({ root, path })
  const response = await fetch(`${apiBaseUrl()}/plugins/workspace/file?${params}`)
  if (!response.ok) await parseDetailOrThrow(response, 'GET /plugins/workspace/file')
  return response.json()
}

export async function writePluginWorkspaceFile(
  root: string,
  path: string,
  content: string,
): Promise<PluginWorkspaceMutationResponse> {
  const response = await fetch(`${apiBaseUrl()}/plugins/workspace/file`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ root, path, content }),
  })
  if (!response.ok) await parseDetailOrThrow(response, 'PUT /plugins/workspace/file')
  return response.json()
}

export async function createPluginWorkspaceEntry(
  root: string,
  path: string,
  kind: 'file' | 'directory',
): Promise<PluginWorkspaceMutationResponse> {
  const response = await fetch(`${apiBaseUrl()}/plugins/workspace/entry`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ root, path, kind }),
  })
  if (!response.ok) await parseDetailOrThrow(response, 'POST /plugins/workspace/entry')
  return response.json()
}

export async function deletePluginWorkspaceEntry(
  root: string,
  path: string,
): Promise<PluginWorkspaceMutationResponse> {
  const response = await fetch(`${apiBaseUrl()}/plugins/workspace/entry`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ root, path }),
  })
  if (!response.ok) await parseDetailOrThrow(response, 'DELETE /plugins/workspace/entry')
  return response.json()
}

export async function getPluginCredentials(id: string): Promise<PluginCredentialState> {
  const response = await fetch(
    `${apiBaseUrl()}/plugins/${encodeURIComponent(id)}/credentials`,
  )
  if (!response.ok) await parseDetailOrThrow(response, 'GET /plugins/:id/credentials')
  return response.json()
}

export async function updatePluginCredentials(
  id: string,
  values: Record<string, string | boolean | null>,
): Promise<PluginCredentialState> {
  const response = await fetch(
    `${apiBaseUrl()}/plugins/${encodeURIComponent(id)}/credentials`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ values }),
    },
  )
  if (!response.ok) await parseDetailOrThrow(response, 'PUT /plugins/:id/credentials')
  return response.json()
}

export async function clearPluginCredentials(id: string): Promise<PluginCredentialState> {
  const response = await fetch(
    `${apiBaseUrl()}/plugins/${encodeURIComponent(id)}/credentials`,
    { method: 'DELETE' },
  )
  if (!response.ok) await parseDetailOrThrow(response, 'DELETE /plugins/:id/credentials')
  return response.json()
}
