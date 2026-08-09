/** Portable Agent Plugins lifecycle API. */

import { apiBaseUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'
import type {
  PluginInspection,
  PluginListResponse,
  PluginOperationResponse,
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
  skill_name?: string
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
