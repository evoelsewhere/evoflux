import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileCode, Loader2, Network, RefreshCw, Search } from 'lucide-react'
import { getCodeGraphStatus, reindexCodeGraph, searchCodeGraph } from '@/api/client'
import { queryKeys } from '@/queries'
import type { CodeGraphNode, WorkspaceFileInfo } from '@/api/types'

function nodeToFile(node: CodeGraphNode): WorkspaceFileInfo {
  return {
    path: node.file_path,
    name: node.file_path.split('/').pop() ?? node.file_path,
    size: 0,
    mtime: 0,
    mime: 'text/plain',
  }
}

function StatCount({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col">
      <span className="font-mono text-sm font-semibold text-(--color-text)">{value}</span>
      <span className="text-xs uppercase tracking-[0.12em] text-(--color-text-subtle)">{label}</span>
    </div>
  )
}

export function CodeGraphPanel({
  workspace,
  onFileSelect,
}: {
  workspace: string
  onFileSelect?: (file: WorkspaceFileInfo | null) => void
}) {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(query.trim()), 250)
    return () => window.clearTimeout(id)
  }, [query])

  const status = useQuery({
    queryKey: queryKeys.codeGraph.status(workspace),
    queryFn: () => getCodeGraphStatus(workspace),
    staleTime: 5_000,
    // While a background index is running, poll so the panel reflects progress
    // and flips to the indexed view as soon as it finishes — this also restores
    // the "Indexing…" state after a page reload (the flag lives server-side).
    refetchInterval: (query) => (query.state.data?.indexing ? 800 : false),
  })

  const indexed = status.data?.indexed ?? false
  const serverIndexing = status.data?.indexing ?? false
  const indexError = status.data?.index_error ?? null
  const indexProgress = status.data?.index_progress ?? null
  const indexMessage = status.data?.index_message ?? null

  const results = useQuery({
    queryKey: queryKeys.codeGraph.search(workspace, debounced),
    queryFn: () => searchCodeGraph(workspace, debounced, { limit: 30 }),
    enabled: indexed && debounced.length > 0,
    staleTime: 5_000,
  })

  const reindex = useMutation({
    mutationFn: (full: boolean) => reindexCodeGraph(workspace, { full }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.codeGraph.all(workspace) })
    },
  })

  const nodes = results.data?.nodes ?? []
  const reindexing = reindex.isPending || serverIndexing

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Status header */}
      <div className="border-b border-(--color-border) px-3 py-3">
        {status.isLoading ? (
          <p className="text-xs text-(--color-text-subtle)">Loading index status…</p>
        ) : status.isError ? (
          <p className="text-xs text-(--color-error)">Failed to load index status</p>
        ) : !indexed ? (
          <div className="flex flex-col items-start gap-2">
            {serverIndexing ? (
              <div className="flex w-full flex-col gap-1.5">
                <p className="inline-flex items-center gap-1.5 text-xs text-(--color-text-subtle)">
                  <Loader2 size={13} className="animate-spin" />
                  {indexMessage || 'Building index…'}
                </p>
                {indexProgress != null && (
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-(--color-border)">
                    <div
                      className="h-full rounded-full bg-(--color-accent) transition-all duration-300"
                      style={{ width: `${Math.round(indexProgress * 100)}%` }}
                    />
                  </div>
                )}
              </div>
            ) : (
              <>
                <p className="text-xs text-(--color-text-subtle)">No code graph for this workspace yet.</p>
                {indexError && (
                  <p className="text-xs text-(--color-error)">Last index failed: {indexError}</p>
                )}
                <button
                  type="button"
                  onClick={() => reindex.mutate(false)}
                  disabled={reindexing}
                  className="inline-flex items-center gap-1.5 rounded-md bg-(--color-accent) px-2.5 py-1.5 text-xs font-medium text-(--color-accent-fg) hover:opacity-90 disabled:opacity-60"
                >
                  {reindexing ? <Loader2 size={13} className="animate-spin" /> : <Network size={13} />}
                  {reindexing ? 'Building…' : 'Build index'}
                </button>
              </>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-4">
              <StatCount label="Files" value={status.data?.files ?? 0} />
              <StatCount label="Symbols" value={status.data?.nodes ?? 0} />
              <StatCount label="Edges" value={status.data?.edges ?? 0} />
            </div>
            {serverIndexing && (
              <div className="flex w-full flex-col gap-1">
                <p className="inline-flex items-center gap-1.5 text-xs text-(--color-text-subtle)">
                  <Loader2 size={11} className="animate-spin" />
                  {indexMessage || 'Reindexing…'}
                </p>
                {indexProgress != null && (
                  <div className="h-1 w-full overflow-hidden rounded-full bg-(--color-border)">
                    <div
                      className="h-full rounded-full bg-(--color-accent) transition-all duration-300"
                      style={{ width: `${Math.round(indexProgress * 100)}%` }}
                    />
                  </div>
                )}
              </div>
            )}
            {indexError && (
              <p className="text-xs text-(--color-error)">Last index failed: {indexError}</p>
            )}
          </div>
        )}
      </div>

      {/* Search */}
      {indexed && (
        <div className="border-b border-(--color-border) p-2">
          <div className="flex items-center gap-1.5 rounded-md bg-(--bg-key) px-2 py-1.5">
            <Search size={13} className="shrink-0 text-(--color-text-subtle)" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search symbols (functions, classes…)"
              className="min-w-0 flex-1 bg-transparent text-xs text-(--color-text) outline-none placeholder:text-(--color-text-subtle)"
            />
            {results.isFetching && <Loader2 size={12} className="shrink-0 animate-spin text-(--color-text-subtle)" />}
          </div>
        </div>
      )}

      {/* Results */}
      <div className="min-h-0 flex-1 overflow-auto p-2">
        {!indexed ? null : debounced.length === 0 ? (
          <p className="px-2 py-4 text-xs text-(--color-text-subtle)">Type to search the code graph.</p>
        ) : results.isLoading ? (
          <p className="px-2 py-4 text-xs text-(--color-text-subtle)">Searching…</p>
        ) : results.isError ? (
          <p className="px-2 py-4 text-xs text-(--color-error)">Search failed</p>
        ) : nodes.length === 0 ? (
          <p className="px-2 py-4 text-xs text-(--color-text-subtle)">No symbols match “{debounced}”.</p>
        ) : (
          <div className="space-y-0.5">
            {nodes.map((node) => (
              <button
                key={node.id}
                type="button"
                onClick={() => onFileSelect?.(nodeToFile(node))}
                className="flex w-full items-start gap-2 rounded px-2 py-1.5 text-left text-xs text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                title={`${node.qualified_name} — ${node.file_path}:${node.line_start}`}
              >
                <FileCode size={13} className="mt-0.5 shrink-0 text-(--color-accent)" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5">
                    <span className="truncate font-mono font-medium text-(--color-text)">{node.name}</span>
                    <span className="shrink-0 rounded bg-(--bg-key) px-1 py-0.5 font-mono text-xs uppercase tracking-wide text-(--color-text-subtle)">{node.kind}</span>
                  </span>
                  <span className="mt-0.5 flex items-center gap-1 truncate font-mono text-xs text-(--color-text-subtle)">
                    {node.file_path}:{node.line_start}
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Reindex footer */}
      {indexed && (
        <button
          type="button"
          onClick={() => reindex.mutate(false)}
          disabled={reindexing}
          className="flex items-center justify-center gap-1.5 border-t border-(--color-border) px-3 py-2 text-xs text-(--color-text-muted) hover:bg-(--bg-key) disabled:opacity-60"
          title="Re-index changed files"
        >
          {reindexing ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          {reindexing ? 'Indexing…' : 'Reindex'}
        </button>
      )}
    </div>
  )
}
