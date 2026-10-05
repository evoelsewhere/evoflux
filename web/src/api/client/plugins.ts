/** Portable Agent Plugins lifecycle API. */

import { apiBaseUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'
import { stripExtendedPathPrefix } from '@/lib/workspace-path-utils'
import type {
  PluginInspection,
  PluginCredentialState,
  PluginListResponse,
  PluginPackageReview,
  PluginPackageFile,
  PluginOperationResponse,
  MarketplaceCreateRequest,
  MarketplacePlugin,
  MarketplacePluginPreview,
  MarketplaceSource,
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
  enabled = false,
): Promise<PluginOperationResponse> {
  const response = await fetch(`${apiBaseUrl()}/plugins/install`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, mode, enabled }),
  })
  if (!response.ok) await parseDetailOrThrow(response, 'POST /plugins/install')
  return response.json()
}

export async function uploadPlugin(
  file: File,
  enabled = false,
): Promise<PluginOperationResponse> {
  const body = new FormData()
  body.append('archive', file)
  const response = await fetch(
    `${apiBaseUrl()}/plugins/upload?enabled=${enabled ? 'true' : 'false'}`,
    {
      method: 'POST',
      body,
    },
  )
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
    `${apiBaseUrl()}/plugins/workspace/tree?root=${encodeURIComponent(stripExtendedPathPrefix(root))}`,
  )
  if (!response.ok) await parseDetailOrThrow(response, 'GET /plugins/workspace/tree')
  return response.json()
}

export async function readPluginWorkspaceFile(
  root: string,
  path: string,
): Promise<PluginWorkspaceFileResponse> {
  const params = new URLSearchParams({ root: stripExtendedPathPrefix(root), path })
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

export async function listMarketplaces(): Promise<MarketplaceSource[]> {
  const response = await fetch(`${apiBaseUrl()}/plugins/marketplaces`)
  if (!response.ok) await parseDetailOrThrow(response, 'GET /plugins/marketplaces')
  return response.json()
}

export async function addMarketplace(body: MarketplaceCreateRequest): Promise<MarketplaceSource> {
  const response = await fetch(`${apiBaseUrl()}/plugins/marketplaces`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) await parseDetailOrThrow(response, 'POST /plugins/marketplaces')
  return response.json()
}

export async function syncMarketplace(id: string): Promise<MarketplaceSource> {
  const response = await fetch(
    `${apiBaseUrl()}/plugins/marketplaces/${encodeURIComponent(id)}/sync`,
    { method: 'POST' },
  )
  if (!response.ok) await parseDetailOrThrow(response, 'POST /plugins/marketplaces/:id/sync')
  return response.json()
}

export async function removeMarketplace(id: string): Promise<MarketplaceSource> {
  const response = await fetch(
    `${apiBaseUrl()}/plugins/marketplaces/${encodeURIComponent(id)}`,
    { method: 'DELETE' },
  )
  if (!response.ok) await parseDetailOrThrow(response, 'DELETE /plugins/marketplaces/:id')
  return response.json()
}

export async function searchMarketplacePlugins(
  query: string,
  marketplaceId?: string,
): Promise<MarketplacePlugin[]> {
  const params = new URLSearchParams()
  if (query.trim()) params.set('q', query.trim())
  if (marketplaceId) params.set('marketplace_id', marketplaceId)
  const suffix = params.size ? `?${params.toString()}` : ''
  const response = await fetch(`${apiBaseUrl()}/plugins/marketplaces/plugins${suffix}`)
  if (!response.ok) await parseDetailOrThrow(response, 'GET /plugins/marketplaces/plugins')
  return response.json()
}

export async function prepareMarketplacePlugin(
  marketplaceId: string,
  pluginName: string,
): Promise<MarketplacePluginPreview> {
  const response = await fetch(
    `${apiBaseUrl()}/plugins/marketplaces/${encodeURIComponent(marketplaceId)}`
      + `/plugins/${encodeURIComponent(pluginName)}/prepare`,
    { method: 'POST' },
  )
  if (!response.ok) await parseDetailOrThrow(response, 'POST /plugins/marketplaces/:id/plugins/:name/prepare')
  return response.json()
}

export async function installMarketplacePlugin(
  previewId: string,
  allowPartial = false,
): Promise<PluginOperationResponse> {
  const response = await fetch(`${apiBaseUrl()}/plugins/marketplaces/install`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ preview_id: previewId, allow_partial: allowPartial }),
  })
  if (!response.ok) await parseDetailOrThrow(response, 'POST /plugins/marketplaces/install')
  return response.json()
}

function packageReviewUrl(target: 'preview' | 'installation', id: string): string {
  const resource = target === 'preview' ? `previews/${encodeURIComponent(id)}` : encodeURIComponent(id)
  return `${apiBaseUrl()}/plugins/${resource}/files`
}

export async function getPluginPackageReview(target: 'preview' | 'installation', id: string): Promise<PluginPackageReview> {
  const response = await fetch(packageReviewUrl(target, id))
  if (!response.ok) await parseDetailOrThrow(response, 'GET /plugins/:resource/files')
  return response.json()
}

export async function getPluginPackageFile(target: 'preview' | 'installation', id: string, path: string): Promise<PluginPackageFile> {
  const response = await fetch(`${packageReviewUrl(target, id)}?${new URLSearchParams({ path })}`)
  if (!response.ok) await parseDetailOrThrow(response, 'GET /plugins/:resource/files?path')
  return response.json()
}
