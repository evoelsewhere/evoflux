import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  Check,
  ChevronDown,
  FileCode2,
  GitBranch,
  Loader2,
  Network,
  RefreshCw,
  Search,
  X,
} from 'lucide-react'
import { getProjectCodeGraphData } from '@/api/client'
import type {
  CodeGraphNode,
  CodingProject,
  ProjectRepoStatus,
  WorkspaceFileInfo,
} from '@/api/types'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { useProjectCodeGraph } from '@/hooks/useProjectCodeGraph'
import { getIntlLocale } from '@/i18n'
import { cn } from '@/lib/utils'
import { queryKeys } from '@/queries/keys'
import { buildSpatialData } from './repoGraphSpatialData'
import { RepoGraphSpatial } from './RepoGraphSpatial'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from './ui/dropdown-menu'

// Canvas rendering stays responsive at this density while giving the explorer
// enough topology to read as a real project constellation instead of a sample.
const NODE_LIMIT = 500
const EDGE_LIMIT = 2_000

function isRepoData(data: ProjectRepoStatus | CodeGraphNode): data is ProjectRepoStatus {
  return 'indexed' in data
}

function repoLabel(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

function compactNumber(value: number): string {
  return new Intl.NumberFormat(getIntlLocale(), {
    notation: value >= 1_000 ? 'compact' : 'standard',
    maximumFractionDigits: 1,
  }).format(value)
}

export interface RepoGraphModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  project: CodingProject
  onFileSelect?: (file: WorkspaceFileInfo | null) => void
}

export function RepoGraphModal({ open, onOpenChange, project, onFileSelect }: RepoGraphModalProps) {
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [hiddenRepos, setHiddenRepos] = useState<Set<string>>(new Set())
  const { repos: liveRepos, summary, reindex, isBusy } = useProjectCodeGraph(project.id)

  const graphQuery = useQuery({
    queryKey: queryKeys.projects.codeGraphData(project.id, NODE_LIMIT, EDGE_LIMIT),
    queryFn: () => getProjectCodeGraphData(project.id, {
      nodeLimitPerRepo: NODE_LIMIT,
      edgeLimitPerRepo: EDGE_LIMIT,
    }),
    enabled: open && summary.indexed > 0,
    staleTime: 30_000,
  })

  const data = graphQuery.data
  const repos = useMemo(
    () => (liveRepos.length > 0 ? liveRepos : data?.repos ?? []),
    [data?.repos, liveRepos],
  )
  const spatialData = useMemo(() => {
    if (!data) return null
    return buildSpatialData(
      repos,
      data.nodes,
      data.edges,
      data.cross_repo_edges,
      data.total_node_count,
      data.total_edge_count,
      data.node_limit_per_repo,
      data.edge_limit_per_repo,
    )
  }, [data, repos])

  const selectedNode = useMemo(() => {
    if (!spatialData || !selectedId) return null
    return spatialData.nodeById.get(selectedId) ?? null
  }, [spatialData, selectedId])

  const selectedConnections = useMemo(() => {
    if (!spatialData || !selectedNode) return []
    return (spatialData.edgesByNodeId.get(selectedNode.id) ?? [])
      .map((edge) => {
        const peerId = edge.source === selectedNode.id ? edge.target : edge.source
        const peer = spatialData.nodeById.get(peerId)
        return {
          id: edge.id,
          peerId,
          peerLabel: peer?.label ?? peerId.slice(0, 8),
          kind: edge.kind,
          crossRepo: edge.crossRepo,
          status: edge.status,
        }
      })
      .sort((a, b) => Number(b.crossRepo) - Number(a.crossRepo))
  }, [spatialData, selectedNode])

  const selectedFile = useMemo<WorkspaceFileInfo | null>(() => {
    if (!selectedNode || isRepoData(selectedNode.data)) return null
    const repo = repos.find((item) => item.workspace_id === selectedNode.workspaceId)
    if (!repo) return null
    return {
      path: selectedNode.data.file_path,
      name: selectedNode.data.file_path.split(/[\\/]/).pop() ?? selectedNode.data.file_path,
      size: 0,
      mtime: 0,
      mime: 'text/plain',
      sourceWorkspace: repo.path,
    }
  }, [repos, selectedNode])

  const toggleRepo = (workspaceId: string) => {
    setHiddenRepos((previous) => {
      const next = new Set(previous)
      if (next.has(workspaceId)) next.delete(workspaceId)
      else next.add(workspaceId)
      return next
    })
    setSelectedId(null)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="flex !h-[94dvh] !max-h-[94dvh] !w-[96vw] !max-w-[96vw] flex-col gap-0 overflow-hidden !rounded-xl border-(--color-border-strong) bg-(--bg-page) p-0 text-(--color-text) shadow-2xl"
      >
        <header className="shrink-0 border-b border-(--color-border) bg-(--bg-card)">
          <div className="flex min-h-14 items-center gap-3 px-4">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-(--accent-blue)/10 text-(--accent-blue)">
              <Network size={15} />
            </span>
            <div className="min-w-0">
              <DialogTitle className="truncate text-sm font-semibold">Code graph</DialogTitle>
              <p className="truncate text-[10px] text-(--color-text-subtle)">
                {project.name} · architecture explorer
              </p>
            </div>

            <div className="ml-3 hidden items-center gap-1.5 border-l border-(--color-border) pl-4 lg:flex">
              <span className="rounded-md bg-(--bg-key) px-2 py-1 text-[10px] text-(--color-text-muted)">
                <strong className="font-mono font-semibold text-(--color-text)">{compactNumber(data?.total_node_count ?? summary.symbols)}</strong> symbols
              </span>
              <span className="rounded-md bg-(--bg-key) px-2 py-1 text-[10px] text-(--color-text-muted)">
                <strong className="font-mono font-semibold text-(--color-text)">{compactNumber(data?.total_edge_count ?? summary.relations)}</strong> relations
              </span>
              <span className="rounded-md bg-(--bg-key) px-2 py-1 text-[10px] text-(--color-text-muted)">
                <strong className="font-mono font-semibold text-(--color-text)">{repos.length}</strong> repositories
              </span>
            </div>

            <div className="ml-auto flex items-center gap-1.5">
              <div className="flex h-8 overflow-hidden rounded-md border border-(--color-border) bg-(--bg-card)">
                <button
                  type="button"
                  onClick={() => reindex(false)}
                  disabled={isBusy}
                  className="inline-flex items-center gap-1.5 px-2.5 text-[11px] font-medium text-(--color-text-muted) hover:bg-(--bg-hover) hover:text-(--color-text) disabled:opacity-50"
                >
                  {isBusy ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                  {isBusy ? 'Indexing' : 'Refresh'}
                </button>
                <DropdownMenu>
                  <DropdownMenuTrigger
                    aria-label="Index options"
                    disabled={isBusy}
                    className="border-l border-(--color-border) px-1.5 text-(--color-text-muted) hover:bg-(--bg-hover)"
                  >
                    <ChevronDown size={11} />
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => reindex(true)}>Force full rebuild</DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
              <button
                type="button"
                onClick={() => onOpenChange(false)}
                aria-label="Close code graph"
                className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) hover:bg-(--bg-hover) hover:text-(--color-text)"
              >
                <X size={16} />
              </button>
            </div>
          </div>

          <div className="flex min-h-12 items-center gap-3 border-t border-(--color-border-subtle) bg-(--bg-page)/45 px-4">
            <label className="flex h-8 min-w-0 max-w-xl flex-1 items-center gap-2 rounded-md border border-(--color-border) bg-(--bg-input) px-2.5 focus-within:border-(--color-border-strong)">
              <Search size={13} className="shrink-0 text-(--color-text-subtle)" />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Filter symbols in this view…"
                className="min-w-0 flex-1 bg-transparent text-xs text-(--color-text) outline-none placeholder:text-(--color-text-subtle)"
              />
              {search && (
                <button type="button" onClick={() => setSearch('')} aria-label="Clear graph search" className="text-(--color-text-subtle) hover:text-(--color-text)">
                  <X size={12} />
                </button>
              )}
            </label>

            <span className="ml-auto hidden items-center gap-1.5 rounded-md border border-(--color-border) bg-(--bg-key) px-2 py-1 text-[9px] font-medium text-(--color-text-muted) sm:inline-flex">
              <Network size={10} /> Focused graph
            </span>
          </div>
        </header>

        <div className="flex min-h-0 flex-1 bg-(--terminal-bg)">
          <aside className="flex w-60 shrink-0 flex-col border-r border-(--color-border) bg-(--bg-card) max-lg:w-52 max-md:hidden">
            <div className="border-b border-(--color-border-subtle) px-3 py-3">
              <div className="flex items-center justify-between">
                <p className="text-[9px] font-semibold uppercase tracking-[0.12em] text-(--color-text-subtle)">Repositories</p>
                <span className="font-mono text-[9px] text-(--color-text-subtle)">{repos.length - hiddenRepos.size}/{repos.length}</span>
              </div>
              <p className="mt-1 text-[10px] leading-relaxed text-(--color-text-subtle)">Toggle a repository to focus the graph.</p>
            </div>
            <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
              {repos.map((repo) => {
                const hidden = hiddenRepos.has(repo.workspace_id)
                const progress = Math.round((repo.index_progress ?? 0) * 100)
                return (
                  <button
                    key={repo.workspace_id}
                    type="button"
                    onClick={() => toggleRepo(repo.workspace_id)}
                    aria-pressed={!hidden}
                    className={cn(
                      'flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors hover:bg-(--bg-hover)',
                      hidden && 'opacity-45',
                    )}
                  >
                    <span className={cn(
                      'flex h-4 w-4 shrink-0 items-center justify-center rounded border',
                      hidden ? 'border-(--color-border)' : 'border-(--accent-blue) bg-(--accent-blue) text-white',
                    )}>
                      {!hidden && <Check size={10} />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5">
                        <GitBranch size={10} className="shrink-0 text-(--color-text-subtle)" />
                        <span className="truncate text-[11px] font-medium text-(--color-text)">{repoLabel(repo.path)}</span>
                      </span>
                      <span className="mt-0.5 block truncate pl-4 text-[9px] text-(--color-text-subtle)">
                        {repo.indexing ? `${progress}% · ${repo.index_phase ?? 'indexing'}` : repo.indexed ? `${compactNumber(repo.nodes)} symbols` : 'Not indexed'}
                      </span>
                    </span>
                    {repo.index_error ? (
                      <AlertCircle size={11} className="shrink-0 text-(--color-error)" />
                    ) : repo.indexing ? (
                      <Loader2 size={11} className="shrink-0 animate-spin text-(--accent-blue)" />
                    ) : null}
                  </button>
                )
              })}
            </div>
            <div className="space-y-2 border-t border-(--color-border-subtle) p-3 text-[9px] text-(--color-text-subtle)">
              <div className="flex items-center justify-between"><span>Repository link</span><span className="h-px w-8 bg-(--accent-green)" /></div>
              <div className="flex items-center justify-between"><span>Internal relation</span><span className="h-px w-8 bg-(--color-text-subtle)" /></div>
              <p className="pt-1 leading-relaxed">Drag to move · scroll to zoom · select a node to inspect</p>
            </div>
          </aside>

          <main className="relative min-w-0 flex-1">
            {summary.indexed === 0 ? (
              <div className="flex h-full flex-col items-center justify-center px-6 text-center text-(--color-text-muted)">
                <Network size={28} className="mb-3 text-(--color-text-subtle)" />
                <p className="text-sm font-medium">No graph data yet</p>
                <p className="mt-1 max-w-sm text-xs text-(--color-text-subtle)">Build the project index to discover symbols and relationships.</p>
                <button type="button" onClick={() => reindex(false)} className="mt-4 rounded-md bg-(--color-text) px-3 py-1.5 text-xs font-semibold text-(--bg-page)">Build index</button>
              </div>
            ) : graphQuery.isLoading ? (
              <div className="flex h-full items-center justify-center text-xs text-(--color-text-subtle)">
                <Loader2 size={15} className="mr-2 animate-spin" /> Preparing architecture view…
              </div>
            ) : graphQuery.isError ? (
              <div className="flex h-full flex-col items-center justify-center text-xs text-(--color-error)">
                <AlertCircle size={18} className="mb-2" /> Could not load graph data.
                <button type="button" onClick={() => void graphQuery.refetch()} className="mt-2 text-(--color-text-muted) underline underline-offset-2">Try again</button>
              </div>
            ) : spatialData ? (
              <RepoGraphSpatial
                data={spatialData}
                searchQuery={search}
                selectedId={selectedId}
                onSelect={setSelectedId}
                hiddenRepoIds={hiddenRepos}
              />
            ) : null}
          </main>

          {selectedNode && (
            <aside className="flex w-80 shrink-0 flex-col border-l border-(--color-border) bg-(--bg-card) max-lg:w-72 max-sm:absolute max-sm:inset-y-0 max-sm:right-0 max-sm:z-(--z-drawer)">
              <div className="flex items-start gap-2 border-b border-(--color-border-subtle) p-4">
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-(--accent-blue)/10 text-(--accent-blue)">
                  {isRepoData(selectedNode.data) ? <GitBranch size={13} /> : <FileCode2 size={13} />}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-(--color-text)">{selectedNode.label}</p>
                  <p className="mt-0.5 truncate font-mono text-[9px] text-(--color-text-subtle)" title={selectedNode.fullLabel}>{selectedNode.fullLabel}</p>
                </div>
                <button type="button" onClick={() => setSelectedId(null)} aria-label="Close inspector" className="rounded p-1 text-(--color-text-muted) hover:bg-(--bg-hover)"><X size={14} /></button>
              </div>

              <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
                {isRepoData(selectedNode.data) ? (
                  <>
                    <div className="grid grid-cols-3 gap-1.5">
                      {[
                        ['Files', selectedNode.data.files],
                        ['Symbols', selectedNode.data.nodes],
                        ['Relations', selectedNode.data.edges],
                      ].map(([label, value]) => (
                        <div key={label} className="rounded-md bg-(--bg-key) px-2 py-2 text-center">
                          <p className="font-mono text-xs font-semibold text-(--color-text)">{compactNumber(Number(value))}</p>
                          <p className="mt-0.5 text-[8px] uppercase tracking-wide text-(--color-text-subtle)">{label}</p>
                        </div>
                      ))}
                    </div>
                    <p className="break-all font-mono text-[10px] leading-relaxed text-(--color-text-subtle)">{selectedNode.data.path}</p>
                    {selectedNode.data.index_error && <p className="rounded-md bg-(--color-error)/10 p-2 text-[10px] text-(--color-error)">{selectedNode.data.index_error}</p>}
                  </>
                ) : (
                  <>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-2 text-[10px]">
                      <span className="text-(--color-text-subtle)">Kind</span><span className="text-right font-mono uppercase text-(--color-text)">{selectedNode.data.kind}</span>
                      <span className="text-(--color-text-subtle)">Language</span><span className="text-right font-mono text-(--color-text)">{selectedNode.data.language}</span>
                      <span className="text-(--color-text-subtle)">Lines</span><span className="text-right font-mono text-(--color-text)">{selectedNode.data.line_start}–{selectedNode.data.line_end}</span>
                    </div>
                    <div>
                      <p className="mb-1 text-[8px] font-semibold uppercase tracking-[0.1em] text-(--color-text-subtle)">Source</p>
                      <p className="break-all rounded-md bg-(--bg-key) p-2 font-mono text-[10px] leading-relaxed text-(--color-text-muted)">{selectedNode.data.file_path}</p>
                    </div>
                    {selectedNode.data.signature && (
                      <div>
                        <p className="mb-1 text-[8px] font-semibold uppercase tracking-[0.1em] text-(--color-text-subtle)">Signature</p>
                        <pre className="whitespace-pre-wrap break-all rounded-md bg-(--bg-key) p-2 font-mono text-[10px] leading-relaxed text-(--color-text)">{selectedNode.data.signature}</pre>
                      </div>
                    )}
                    {selectedFile && onFileSelect && (
                      <button
                        type="button"
                        onClick={() => {
                          onFileSelect(selectedFile)
                          onOpenChange(false)
                        }}
                        className="flex h-8 w-full items-center justify-center gap-1.5 rounded-md bg-(--color-text) text-[11px] font-semibold text-(--bg-page) hover:opacity-85"
                      >
                        <FileCode2 size={12} /> Open source file
                      </button>
                    )}
                  </>
                )}

                <section>
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-[8px] font-semibold uppercase tracking-[0.1em] text-(--color-text-subtle)">Connections</p>
                    <span className="font-mono text-[9px] text-(--color-text-subtle)">{selectedConnections.length}</span>
                  </div>
                  {selectedConnections.length === 0 ? (
                    <p className="rounded-md border border-dashed border-(--color-border) px-2 py-3 text-center text-[10px] text-(--color-text-subtle)">No visible connections</p>
                  ) : (
                    <div className="space-y-1">
                      {selectedConnections.map((connection) => (
                        <button
                          key={connection.id}
                          type="button"
                          onClick={() => setSelectedId(connection.peerId)}
                          className="flex w-full items-center gap-2 rounded-md bg-(--bg-key) px-2 py-2 text-left hover:bg-(--bg-hover)"
                        >
                          <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', connection.crossRepo ? 'bg-(--accent-green)' : 'bg-(--color-text-subtle)')} />
                          <span className="min-w-0 flex-1 truncate text-[10px] text-(--color-text)">{connection.peerLabel}</span>
                          <span className="shrink-0 font-mono text-[8px] text-(--color-text-subtle)">{connection.kind}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </section>
              </div>
            </aside>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
