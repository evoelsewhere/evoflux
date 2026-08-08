import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, GitBranch, Grid3X3, Loader2, Network, Search, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { getProjectCodeGraphData } from '@/api/client'
import { queryKeys } from '@/queries/keys'
import { RepoGraphSpatial } from './RepoGraphSpatial'
import { RepoGraphMatrix } from './RepoGraphMatrix'
import { buildSpatialData } from './repoGraphSpatialData'
import type { CodingProject, ProjectRepoStatus, CodeGraphNode } from '@/api/types'
import { getIntlLocale } from '@/i18n'

function isRepoData(data: ProjectRepoStatus | CodeGraphNode): data is ProjectRepoStatus {
  return 'indexed' in data
}

function repoLabel(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

export interface RepoGraphModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  project: CodingProject
}

export function RepoGraphModal({ open, onOpenChange, project }: RepoGraphModalProps) {
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [hiddenRepos, setHiddenRepos] = useState<Set<string>>(new Set())
  const [view, setView] = useState<'spatial' | 'matrix'>('spatial')

  const graphQuery = useQuery({
    queryKey: queryKeys.projects.codeGraphData(project.id),
    queryFn: () => getProjectCodeGraphData(project.id, { nodeLimitPerRepo: 600, edgeLimitPerRepo: 2500 }),
    enabled: open,
    staleTime: 30_000,
  })

  const data = graphQuery.data
  const spatialData = useMemo(() => {
    if (!data) return null
    return buildSpatialData(
      data.repos,
      data.nodes,
      data.edges,
      data.cross_repo_edges,
      data.total_node_count,
      data.total_edge_count,
      data.node_limit_per_repo,
      data.edge_limit_per_repo,
    )
  }, [data])

  const selectedNode = useMemo(() => {
    if (!spatialData || !selectedId) return null
    return spatialData.nodes.find((n) => n.id === selectedId) ?? null
  }, [spatialData, selectedId])

  const selectedConnections = useMemo(() => {
    if (!spatialData || !selectedNode) return []
    const spatialEdges = spatialData.edgesByNodeId.get(selectedNode.id) ?? []
    if (spatialEdges.length > 0) {
      return spatialEdges.map((e) => {
        const peerId = e.source === selectedNode.id ? e.target : e.source
        const peer = spatialData.nodeById.get(peerId)
        return {
          id: e.id,
          peerId,
          peerLabel: peer?.label ?? peerId.slice(0, 8),
          peerRepo: peer?.workspaceId ?? '',
          kind: e.kind,
          crossRepo: e.crossRepo,
          status: e.status,
        }
      }).sort((a, b) => Number(b.crossRepo) - Number(a.crossRepo))
    }

    if (!data) return []
    const results: Array<{
      id: string; peerId: string; peerLabel: string; peerRepo: string
      kind: string; crossRepo: boolean; status?: string
    }> = []

    for (const edge of data.edges) {
      const isSrc = edge.src_id === selectedNode.id
      const isDst = edge.dst_id === selectedNode.id
      if (!isSrc && !isDst) continue
      const peerId = isSrc ? edge.dst_id : edge.src_id
      const peerNode = data.nodes.find((n) => n.id === peerId)
      results.push({
        id: `raw:${edge.id}`, peerId,
        peerLabel: peerNode?.name ?? peerId.slice(0, 8),
        peerRepo: peerNode?.workspace_id ?? '',
        kind: edge.kind, crossRepo: false,
      })
    }

    for (const edge of data.cross_repo_edges) {
      const srcId = edge.src_node_id ?? `repo:${edge.src_workspace_id}`
      const dstId = edge.dst_node_id ?? (edge.dst_workspace_id ? `repo:${edge.dst_workspace_id}` : null)
      if (!dstId) continue
      const isSrc = srcId === selectedNode.id
      const isDst = dstId === selectedNode.id
      if (!isSrc && !isDst) continue
      const peerId = isSrc ? dstId : srcId
      const peerSpatial = spatialData.nodes.find((n) => n.id === peerId)
      const peerApi = peerId.startsWith('repo:') ? null : data.nodes.find((n) => n.id === peerId)
      results.push({
        id: `cross:${edge.id}`, peerId,
        peerLabel: peerSpatial?.label ?? peerApi?.name ?? peerId.slice(0, 8),
        peerRepo: peerApi?.workspace_id ?? edge.dst_workspace_id ?? '',
        kind: edge.kind, crossRepo: true, status: edge.status,
      })
    }

    return results.sort((a, b) => Number(b.crossRepo) - Number(a.crossRepo))
  }, [spatialData, selectedNode, data])

  const toggleRepo = (workspaceId: string) => {
    setHiddenRepos((prev) => {
      const next = new Set(prev)
      if (next.has(workspaceId)) next.delete(workspaceId)
      else next.add(workspaceId)
      return next
    })
  }

  const repos = data?.repos ?? []

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        key={open ? 'repo-graph-open' : undefined}
        showCloseButton={false}
        className="flex !h-[90dvh] !max-h-[90dvh] !w-[90vw] !max-w-[90vw] flex-col gap-0 overflow-hidden !rounded-lg p-0"
      >
        <div className="flex shrink-0 items-center gap-3 border-b border-(--color-border) px-4 py-3">
          <h2 className="truncate text-sm font-semibold text-(--color-text)">Code graph — {project.name}</h2>
          <div className="ml-auto flex items-center gap-2">
            <div className="flex items-center rounded-md border border-(--color-border) bg-(--bg-key) p-0.5">
              <button
                type="button"
                onClick={() => setView('spatial')}
                className={cn(
                  'flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition-colors',
                  view === 'spatial'
                    ? 'bg-(--bg-card) text-(--color-text) shadow-sm'
                    : 'text-(--color-text-muted) hover:text-(--color-text)',
                )}
              >
                <Network size={12} /> Graph
              </button>
              <button
                type="button"
                onClick={() => setView('matrix')}
                className={cn(
                  'flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition-colors',
                  view === 'matrix'
                    ? 'bg-(--bg-card) text-(--color-text) shadow-sm'
                    : 'text-(--color-text-muted) hover:text-(--color-text)',
                )}
              >
                <Grid3X3 size={12} /> Matrix
              </button>
            </div>
            <div className="flex items-center gap-1.5 rounded-md bg-(--bg-key) px-2 py-1.5">
              <Search size={13} className="shrink-0 text-(--color-text-subtle)" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search symbols, files, repos…"
                className="w-56 bg-transparent text-xs text-(--color-text) outline-none placeholder:text-(--color-text-subtle)"
              />
              {graphQuery.isFetching && <Loader2 size={12} className="shrink-0 animate-spin text-(--color-text-subtle)" />}
            </div>
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              className="flex h-7 w-7 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        <div className="relative min-h-0 flex-1 bg-neutral-950">
          {graphQuery.isLoading ? (
            <div className="flex h-full items-center justify-center text-xs text-(--color-text-subtle)">
              <Loader2 size={16} className="mr-2 animate-spin" /> Loading code graph…
            </div>
          ) : graphQuery.isError ? (
            <div className="flex h-full items-center justify-center text-xs text-(--color-error)">Failed to load code graph</div>
          ) : view === 'matrix' && data ? (
            <RepoGraphMatrix repos={data.repos} crossRepoEdges={data.cross_repo_edges} />
          ) : spatialData ? (
            <RepoGraphSpatial
              data={spatialData}
              searchQuery={search}
              selectedId={selectedId}
              onSelect={setSelectedId}
              hiddenRepoIds={hiddenRepos}
            />
          ) : null}

          {repos.length > 1 && (
            <div className="absolute left-0 top-0 z-(--z-header) flex h-full w-52 flex-col gap-1 overflow-y-auto border-r border-(--color-border) bg-(--bg-card)/95 p-3 backdrop-blur-sm">
              <p className="mb-1 text-[10px] font-medium uppercase tracking-wide text-(--color-text-subtle)">Repositories</p>
              {repos.map((repo) => {
                const hidden = hiddenRepos.has(repo.workspace_id)
                return (
                  <button
                    key={repo.workspace_id}
                    type="button"
                    onClick={() => toggleRepo(repo.workspace_id)}
                    className={cn(
                      'flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors',
                      hidden ? 'opacity-40 hover:opacity-70' : 'hover:bg-(--bg-key)',
                    )}
                  >
                    <span
                      className={cn(
                        'flex h-4 w-4 shrink-0 items-center justify-center rounded border',
                        hidden
                          ? 'border-(--color-border)'
                          : 'border-(--accent-blue) bg-(--accent-blue) text-white',
                      )}
                    >
                      {!hidden && <Check size={10} />}
                    </span>
                    <GitBranch size={10} className="shrink-0 text-(--color-text-subtle)" />
                    <span className="min-w-0 flex-1 truncate text-(--color-text)">{repoLabel(repo.path)}</span>
                    {repo.indexed && (
                      <span className="shrink-0 font-mono text-[9px] text-(--color-text-subtle)">{repo.nodes}</span>
                    )}
                  </button>
                )
              })}
              {data && (
                <div className="mt-2 border-t border-(--color-border) pt-2 text-[10px] text-(--color-text-subtle)">
                  <p>{data.total_node_count.toLocaleString(getIntlLocale())} total nodes</p>
                  <p>{data.total_edge_count.toLocaleString(getIntlLocale())} total edges</p>
                </div>
              )}
            </div>
          )}

          {selectedNode && (
            <div className="absolute right-0 top-0 z-(--z-drawer) flex h-full w-80 flex-col gap-3 overflow-y-auto border-l border-(--color-border) bg-(--bg-card) p-4 shadow-xl">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-(--color-text)">{selectedNode.label}</p>
                  <p className="truncate text-[11px] text-(--color-text-subtle)" title={selectedNode.fullLabel}>
                    {selectedNode.fullLabel}
                  </p>
                  <span className="mt-1 inline-block rounded bg-(--bg-key) px-1.5 py-0.5 font-mono text-[10px] uppercase text-(--color-text-subtle)">
                    {selectedNode.kind}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedId(null)}
                  className="shrink-0 rounded p-1 text-(--color-text-muted) hover:bg-(--bg-key)"
                >
                  <X size={14} />
                </button>
              </div>

              {isRepoData(selectedNode.data) && (
                <>
                  <div className="grid grid-cols-3 gap-2 rounded-md bg-(--bg-key) p-2 text-center">
                    <div>
                      <p className="text-sm font-semibold text-(--color-text)">{selectedNode.data.files}</p>
                      <p className="text-[10px] text-(--color-text-subtle)">files</p>
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-(--color-text)">{selectedNode.data.nodes}</p>
                      <p className="text-[10px] text-(--color-text-subtle)">symbols</p>
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-(--color-text)">{selectedNode.data.edges}</p>
                      <p className="text-[10px] text-(--color-text-subtle)">edges</p>
                    </div>
                  </div>
                  {selectedNode.data.indexed && (
                    <p className="text-[11px] text-green-500">✓ Indexed</p>
                  )}
                  {selectedNode.data.indexing && (
                    <p className="text-[11px] text-amber-400">⏳ Indexing… {selectedNode.data.index_message ?? ''}</p>
                  )}
                  {selectedNode.data.index_error && (
                    <p className="rounded-md bg-(--color-error)/10 px-2 py-1.5 text-[11px] text-(--color-error)">{selectedNode.data.index_error}</p>
                  )}
                </>
              )}

              {!isRepoData(selectedNode.data) && (
                <div className="space-y-1.5 text-[11px]">
                  <div className="flex justify-between text-(--color-text-subtle)">
                    <span>Kind</span>
                    <span className="font-mono uppercase text-(--color-text)">{selectedNode.data.kind}</span>
                  </div>
                  <div className="flex justify-between text-(--color-text-subtle)">
                    <span>Language</span>
                    <span className="font-mono text-(--color-text)">{selectedNode.data.language}</span>
                  </div>
                  <div className="flex justify-between text-(--color-text-subtle)">
                    <span>File</span>
                    <span className="max-w-[160px] truncate font-mono text-(--color-text)" title={selectedNode.data.file_path}>
                      {selectedNode.data.file_path.split(/[\\/]/).pop()}
                    </span>
                  </div>
                  <div className="flex justify-between text-(--color-text-subtle)">
                    <span>Lines</span>
                    <span className="font-mono text-(--color-text)">{selectedNode.data.line_start}–{selectedNode.data.line_end}</span>
                  </div>
                  {selectedNode.data.signature && (
                    <div className="mt-1 rounded-md bg-(--bg-key) p-2">
                      <p className="mb-0.5 text-[9px] uppercase tracking-wide text-(--color-text-subtle)">Signature</p>
                      <pre className="whitespace-pre-wrap break-all font-mono text-[10px] text-(--color-text)">{selectedNode.data.signature}</pre>
                    </div>
                  )}
                  {selectedNode.data.docstring && (
                    <div className="mt-1 rounded-md bg-(--bg-key) p-2">
                      <p className="mb-0.5 text-[9px] uppercase tracking-wide text-(--color-text-subtle)">Docstring</p>
                      <p className="whitespace-pre-wrap text-[10px] text-(--color-text-muted)">{selectedNode.data.docstring}</p>
                    </div>
                  )}
                </div>
              )}

              <div>
                <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-(--color-text-subtle)">
                  Connections ({selectedConnections.length})
                </p>
                {selectedConnections.length === 0 ? (
                  <p className="text-[11px] text-(--color-text-subtle)">No connections found.</p>
                ) : (
                  <div className="space-y-1">
                    {selectedConnections.map((c) => {
                      const statusText = c.crossRepo
                        ? c.status === 'resolved' ? 'resolved' : c.status === 'unresolved' ? 'unresolved' : 'rejected'
                        : c.kind
                      const statusClass =
                        c.status === 'resolved' ? 'text-green-500'
                          : c.status === 'unresolved' ? 'text-(--color-error)'
                            : 'text-(--color-text-subtle)'
                      return (
                        <button
                          key={c.id}
                          type="button"
                          onClick={() => setSelectedId(c.peerId)}
                          className="flex w-full items-center justify-between gap-2 rounded-md bg-(--bg-key) px-2 py-1.5 text-left text-xs hover:bg-(--bg-key)/70"
                        >
                          <span className="min-w-0 flex-1 truncate text-(--color-text)">{c.peerLabel}</span>
                          <span className={cn('shrink-0 font-mono text-[10px]', c.crossRepo ? statusClass : 'text-(--color-text-subtle)')}>
                            {c.crossRepo ? statusText : c.kind}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
