/** Client adapters for the unified /api/code-context API. */

import { apiBaseUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'
import type {
  CodeGraphFreshnessPolicy,
  CodeGraphFreshnessResponse,
  CodeGraphLanguageCapability,
  CodeGraphNavigateResponse,
  CodeGraphNode,
  CodeGraphOperation,
  CodeGraphReindexResponse,
  CodeGraphSearchResponse,
  CodeGraphStatusResponse,
  CodeGraphSymbol,
} from '../types'

interface RawStatus {
  indexed: boolean
  files: number
  chunks: number
  symbols: number
  relations: number
  languages: string[]
  graph_languages: string[]
  version: string | null
  indexing: boolean
  index_error: string | null
}

interface RawSymbol {
  id: string
  repository: string
  file_path: string
  language: string
  kind: string
  name: string
  qualified_name: string
  line_start: number
  line_end: number
  signature: string | null
  source: string | null
}

interface RawQuery {
  action: string
  query: string
  strategy: string
  index_version: string | null
  hits: Array<{
    repository: string
    file_path: string
    language: string
    line_start: number
    line_end: number
    content: string
    score: number
    symbol: string | null
    repository_path: string | null
  }>
  matches: RawSymbol[]
  relations: Array<{
    kind: string
    depth: number
    cross_repo: boolean
    source: RawSymbol
    target: RawSymbol
    callsite_file: string
    callsite_line: number
    callsite_source: string | null
  }>
  suggestions: RawSymbol[]
  limitations: string[]
  truncated: boolean
}

function statusParams(workspace: string): URLSearchParams {
  return new URLSearchParams({ workspace })
}

async function rawStatus(workspace: string): Promise<RawStatus> {
  const res = await fetch(`${apiBaseUrl()}/code-context/status?${statusParams(workspace)}`, {
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) await parseDetailOrThrow(res, 'getCodeContextStatus')
  return res.json()
}

export async function getCodeGraphStatus(workspace: string): Promise<CodeGraphStatusResponse> {
  const value = await rawStatus(workspace)
  return {
    indexed: value.indexed,
    files: value.files,
    nodes: value.symbols,
    edges: value.relations,
    indexing: value.indexing,
    index_phase: null,
    index_progress: null,
    index_message: null,
    index_error: value.index_error,
  }
}

async function runQuery(
  workspace: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<RawQuery> {
  const res = await fetch(`${apiBaseUrl()}/code-context/query?${statusParams(workspace)}`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) await parseDetailOrThrow(res, 'queryCodeContext')
  return res.json()
}

export async function searchCodeGraph(
  workspace: string,
  query: string,
  options?: { kind?: string; limit?: number },
): Promise<CodeGraphSearchResponse> {
  const result = await runQuery(workspace, {
    action: 'search',
    query,
    limit: options?.limit ?? 20,
    refresh: true,
  })
  const nodes: CodeGraphNode[] = result.hits.map((hit) => {
    const qualified = hit.symbol ?? hit.file_path
    return {
      id: `${hit.repository}:${hit.file_path}:${hit.line_start}`,
      workspace_id: workspace,
      kind: options?.kind ?? 'source',
      name: qualified.split('.').pop() ?? qualified,
      qualified_name: qualified,
      file_path: hit.file_path,
      language: hit.language,
      line_start: hit.line_start,
      line_end: hit.line_end,
      signature: null,
      docstring: null,
    }
  })
  return { nodes }
}

function symbol(value: RawSymbol): CodeGraphSymbol {
  return {
    repository: value.repository,
    file_path: value.file_path,
    line_start: value.line_start,
    line_end: value.line_end,
    symbol: value.qualified_name,
    kind: value.kind,
    language: value.language,
    signature: value.signature,
    resolution: 'exact',
    source: value.source,
  }
}

export async function navigateCodeGraph(
  workspace: string,
  symbolName: string,
  options?: {
    operation?: CodeGraphOperation
    freshness?: CodeGraphFreshnessPolicy
    path?: string
    repository?: string
    depth?: number
    limit?: number
    signal?: AbortSignal
  },
): Promise<CodeGraphNavigateResponse> {
  const operation = options?.operation ?? 'definition'
  const result = await runQuery(
    workspace,
    {
      action: operation,
      query: symbolName,
      repository: options?.repository,
      paths: options?.path ? [options.path] : null,
      depth: options?.depth ?? 1,
      limit: options?.limit ?? 40,
      refresh: options?.freshness !== 'fast',
    },
    options?.signal,
  )
  return {
    symbol: symbolName,
    operation,
    strategy: result.strategy,
    graph_version: result.index_version,
    working_tree_revision: result.index_version ?? 'unavailable',
    freshness: result.index_version ? 'fresh' : 'unavailable',
    dirty_files: 0,
    pending_edges: 0,
    matches: result.matches.map(symbol),
    relations: result.relations.map((item) => ({
      kind: item.kind,
      depth: item.depth,
      cross_repo: item.cross_repo,
      source_symbol: item.source.qualified_name,
      source_location: `${item.source.repository}/${item.source.file_path}:${item.source.line_start}`,
      target_symbol: item.target.qualified_name,
      target_location: `${item.target.repository}/${item.target.file_path}:${item.target.line_start}`,
      callsite_location: `${item.source.repository}/${item.callsite_file}:${item.callsite_line}`,
      callsite_source: item.callsite_source,
    })),
    suggestions: result.suggestions.map(symbol),
    capabilities: [],
    limitations: result.limitations,
    truncated: result.truncated,
  }
}

export async function getCodeGraphFreshness(workspace: string): Promise<CodeGraphFreshnessResponse> {
  const value = await rawStatus(workspace)
  return {
    graph_version: value.version,
    working_tree_revision: value.version ?? 'unavailable',
    freshness: value.version ? 'fresh' : 'unavailable',
    indexed_files: value.files,
    dirty_files: 0,
    change_source: 'desired-state-refresh',
  }
}

export async function getCodeGraphCapabilities(
  workspace: string,
): Promise<CodeGraphLanguageCapability[]> {
  const value = await rawStatus(workspace)
  return value.languages.map((language) => ({
    language,
    extensions: [],
    graph: value.graph_languages.includes(language),
    lsp: false,
    indexed_files: value.files,
    workspace_files: value.files,
    coverage: 1,
  }))
}

export async function reindexCodeGraph(
  workspace: string,
  options?: { full?: boolean },
): Promise<CodeGraphReindexResponse> {
  const res = await fetch(`${apiBaseUrl()}/code-context/index?${statusParams(workspace)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ full: options?.full ?? false }),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'indexCodeContext')
  return { indexing: false, already_running: false }
}
