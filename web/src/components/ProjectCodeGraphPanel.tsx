/**
 * ProjectCodeGraphPanel — project-wide code graph browsing, no repo picker.
 *
 * Mirrors CodeGraphPanel.tsx's UX (status header, debounced search, result
 * list) but fans out across every repo in the project via the project-scoped
 * endpoints (`/team/projects/{id}/code-graph/status|search`, backed by
 * `search_across_workspaces` server-side) instead of a single `workspace`
 * query param. Single-repo sessions keep using CodeGraphPanel unchanged —
 * this component only mounts in project mode.
 *
 * Indexing itself is triggered from CrossRepoLinksPanel's single Index/
 * Reindex button (rendered above this panel in the Graph tab) — this
 * component is read-only status + search, not a second place to kick off
 * indexing.
 */

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileCode, Loader2, Search } from 'lucide-react'
import { getProjectCodeGraphStatus, searchProjectCodeGraph } from '@/api/client'
import { queryKeys } from '@/queries/keys'
import type { CodingProject, ProjectCodeSearchResult, WorkspaceFileInfo } from '@/api/types'

function repoLabel(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

function nodeToFile(result: ProjectCodeSearchResult): WorkspaceFileInfo {
  const { node, path } = result
  return {
    path: node.file_path,
    name: node.file_path.split(/[\\/]/).pop() ?? node.file_path,
    size: 0,
    mtime: 0,
    mime: 'text/plain',
    sourceWorkspace: path,
  }
}

export interface ProjectCodeGraphPanelProps {
  project: CodingProject
  onFileSelect?: (file: WorkspaceFileInfo | null) => void
}

export function ProjectCodeGraphPanel({ project, onFileSelect }: ProjectCodeGraphPanelProps) {
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(query.trim()), 250)
    return () => window.clearTimeout(id)
  }, [query])

  const statusQuery = useQuery({
    queryKey: queryKeys.projects.codeGraphStatus(project.id),
    queryFn: () => getProjectCodeGraphStatus(project.id),
    staleTime: 5_000,
    refetchInterval: (q) => (q.state.data?.some((r) => r.indexing) ? 800 : false),
  })

  const repos = statusQuery.data ?? []
  const indexedCount = repos.filter((r) => r.indexed).length
  const notIndexed = repos.filter((r) => !r.indexed)
  const anyIndexed = indexedCount > 0

  const results = useQuery({
    queryKey: queryKeys.projects.codeGraphSearch(project.id, debounced),
    queryFn: () => searchProjectCodeGraph(project.id, debounced, { limitPerRepo: 10 }),
    enabled: debounced.length > 0,
    staleTime: 5_000,
  })

  const matches = results.data?.results ?? []
  const grouped = new Map<string, ProjectCodeSearchResult[]>()
  for (const m of matches) {
    const list = grouped.get(m.path) ?? []
    list.push(m)
    grouped.set(m.path, list)
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Status header */}
      <div className="border-b border-(--color-border) px-3 py-3">
        {statusQuery.isLoading ? (
          <p className="text-xs text-(--color-text-subtle)">Loading index status…</p>
        ) : statusQuery.isError ? (
          <p className="text-xs text-(--color-error)">Failed to load index status</p>
        ) : (
          <div className="flex flex-col gap-1.5">
            <p className="text-xs text-(--color-text-muted)">
              {indexedCount}/{repos.length} repos indexed
            </p>
            {notIndexed.map((repo) => (
              <div key={repo.workspace_id} className="flex items-center justify-between gap-2">
                <span className="min-w-0 flex-1 truncate text-xs text-(--color-text-subtle)" title={repo.path}>
                  {repoLabel(repo.path)}
                  {repo.index_error && <span className="ml-1.5 text-(--color-error)">— failed</span>}
                </span>
                {repo.indexing ? (
                  <span className="inline-flex shrink-0 items-center gap-1 text-[10px] text-(--color-text-subtle)">
                    <Loader2 size={11} className="animate-spin" />
                    {repo.index_message || 'Building…'}
                  </span>
                ) : (
                  <span className="shrink-0 text-[10px] text-(--color-text-subtle)">Not indexed yet</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Search */}
      {anyIndexed && (
        <div className="border-b border-(--color-border) p-2">
          <div className="flex items-center gap-1.5 rounded-md bg-(--bg-key) px-2 py-1.5">
            <Search size={13} className="shrink-0 text-(--color-text-subtle)" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search symbols across all repos…"
              className="min-w-0 flex-1 bg-transparent text-xs text-(--color-text) outline-none placeholder:text-(--color-text-subtle)"
            />
            {results.isFetching && <Loader2 size={12} className="shrink-0 animate-spin text-(--color-text-subtle)" />}
          </div>
        </div>
      )}

      {/* Results */}
      <div className="min-h-0 flex-1 overflow-auto p-2">
        {!anyIndexed ? (
          <p className="px-2 py-4 text-xs text-(--color-text-subtle)">Build an index for at least one repo to search.</p>
        ) : debounced.length === 0 ? (
          <p className="px-2 py-4 text-xs text-(--color-text-subtle)">Type to search the code graph across every repo.</p>
        ) : results.isLoading ? (
          <p className="px-2 py-4 text-xs text-(--color-text-subtle)">Searching…</p>
        ) : results.isError ? (
          <p className="px-2 py-4 text-xs text-(--color-error)">Search failed</p>
        ) : matches.length === 0 ? (
          <p className="px-2 py-4 text-xs text-(--color-text-subtle)">No symbols match "{debounced}".</p>
        ) : (
          <div className="space-y-2">
            {[...grouped.entries()].map(([path, group]) => (
              <div key={path}>
                <p className="px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-(--color-text-subtle)">
                  {repoLabel(path)}
                </p>
                <div className="space-y-0.5">
                  {group.map((result) => (
                    <button
                      key={result.node.id}
                      type="button"
                      onClick={() => onFileSelect?.(nodeToFile(result))}
                      className="flex w-full items-start gap-2 rounded px-2 py-1.5 text-left text-xs text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                      title={`${result.node.qualified_name} — ${result.node.file_path}:${result.node.line_start}`}
                    >
                      <FileCode size={13} className="mt-0.5 shrink-0 text-(--color-accent)" />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-1.5">
                          <span className="truncate font-mono font-medium text-(--color-text)">{result.node.name}</span>
                          <span className="shrink-0 rounded bg-(--bg-key) px-1 py-0.5 font-mono text-xs uppercase tracking-wide text-(--color-text-subtle)">
                            {result.node.kind}
                          </span>
                        </span>
                        <span className="mt-0.5 flex items-center gap-1 truncate font-mono text-xs text-(--color-text-subtle)">
                          {result.node.file_path}:{result.node.line_start}
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

    </div>
  )
}
