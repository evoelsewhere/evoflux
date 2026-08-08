/** Project index controls and dynamically resolved cross-repository links. */

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ChevronDown,
  GitBranch,
  Loader2,
  Maximize2,
  Network,
  RefreshCw,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  getProjectCodeGraphStatus,
  listCrossRepoEdges,
  reindexProjectCodeGraph,
} from '@/api/client'
import { queryKeys } from '@/queries/keys'
import {
  buildRepoLinks,
  edgeBand,
  edgePath,
  layoutRepoNodesCircular,
  repoCountText,
  repoPct,
  repoRingState,
} from './repoGraphShared'
import { RepoGraphModal } from './RepoGraphModal'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from './ui/dropdown-menu'
import type { CodingProject, CrossRepoEdge, ProjectRepoStatus } from '@/api/types'

function RepoGraph({
  project,
  edges,
  repos,
  onExpand,
}: {
  project: CodingProject
  edges: CrossRepoEdge[]
  repos: ProjectRepoStatus[]
  onExpand: () => void
}) {
  const nodes = layoutRepoNodesCircular(project.workspaces)
  const nodeById = new Map(nodes.map((n) => [n.workspaceId, n]))
  const repoByWorkspaceId = new Map(repos.map((r) => [r.workspace_id, r]))
  const links = buildRepoLinks(edges)
  return (
    <div className="group relative h-[190px] shrink-0 overflow-hidden rounded-md border border-(--color-border) bg-(--bg-key)/30">
      <button
        type="button"
        onClick={onExpand}
        title="Expand to full view"
        className="absolute right-1.5 top-1.5 z-(--z-drawer) flex h-6 w-6 items-center justify-center rounded-md bg-(--bg-card)/90 text-(--color-text-muted) opacity-0 shadow-sm transition-opacity hover:text-(--color-text) group-hover:opacity-100"
      >
        <Maximize2 size={12} />
      </button>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 z-0 h-full w-full">
        <defs>
          <marker id="repo-graph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className="fill-(--color-text-subtle)" />
          </marker>
        </defs>
        {links.map((link) => {
          const src = nodeById.get(link.srcId)
          const dst = nodeById.get(link.dstId)
          if (!src || !dst) return null
          // Offset bidirectional pairs (A→B and B→A both present) so their
          // curves bow apart instead of tracing the same arc.
          const hasReverse = links.some((l) => l.srcId === link.dstId && l.dstId === link.srcId)
          const { d, midX, midY } = edgePath(src.cx, src.cy, dst.cx, dst.cy, hasReverse)
          const count = link.resolvedCount + link.unresolvedCount
          const { ratio, strokeClass, fillClass } = edgeBand(link.resolvedCount, link.unresolvedCount)
          const trackWidth = 0.4 + Math.min(count, 20) * 0.05
          return (
            <g key={`${link.srcId}-${link.dstId}`}>
              {/* Track: always visible, carries the arrowhead so direction
                  shows even at 0% resolved. Dashed + tinted red when nothing
                  on this link has resolved yet — a "dead link" needs attention. */}
              <path
                d={d}
                fill="none"
                pathLength={100}
                className={ratio === 0 ? 'stroke-(--color-error)/50' : 'stroke-(--color-border)'}
                strokeWidth={trackWidth}
                strokeDasharray={ratio === 0 ? '2,2' : undefined}
                strokeLinecap="round"
                markerEnd="url(#repo-graph-arrow)"
              />
              {/* Fill: grows outward from the source node like a loading bar
                  bent along the curve — the resolution ratio, visually, not
                  just as a number. */}
              {ratio > 0 && (
                <path
                  d={d}
                  fill="none"
                  pathLength={100}
                  className={cn(strokeClass, 'transition-[stroke-dasharray] duration-500 ease-out')}
                  strokeWidth={trackWidth + 0.3}
                  strokeDasharray={`${ratio * 100} ${100 - ratio * 100}`}
                  strokeLinecap="round"
                />
              )}
              {count >= 2 && (
                <g>
                  <circle cx={midX} cy={midY} r={3.2} className="fill-(--bg-card)" />
                  <text
                    x={midX}
                    y={midY}
                    textAnchor="middle"
                    dominantBaseline="central"
                    style={{ fontSize: '3.2px' }}
                    className={fillClass}
                  >
                    {Math.round(ratio * 100)}%
                  </text>
                </g>
              )}
            </g>
          )
        })}
      </svg>

      {nodes.map((node) => {
        const repo = repoByWorkspaceId.get(node.workspaceId)
        const pct = repoPct(repo)
        const state = repoRingState(repo)
        const pctLabel = repo?.index_error ? '!' : repo?.indexed ? '100%' : repo?.indexing ? `${pct}%` : '—'
        return (
          <div
            key={node.workspaceId}
            title={node.path}
            style={{ left: `${node.cx}%`, top: `${node.cy}%` }}
            className={cn(
              'absolute z-(--z-panel) -translate-x-1/2 -translate-y-1/2 rounded-xl bg-(--bg-card) shadow-sm transition-shadow',
              repo?.index_error ? 'w-[92px] bg-(--color-error)/5 ring-1 ring-(--color-error)/30' : 'w-[88px]',
            )}
          >
            {/* Traced-border progress ring: the card's own rounded outline
                doubles as the "download progress" indicator — no separate
                gauge competing for space inside a small card. */}
            <svg viewBox="0 0 100 52" className="pointer-events-none absolute inset-0 h-full w-full">
              <rect
                x="1" y="1" width="98" height="50" rx="8" pathLength={100}
                fill="none" className="stroke-(--color-border)" strokeWidth={2} strokeOpacity={0.35}
              />
              <rect
                x="1" y="1" width="98" height="50" rx="8" pathLength={100}
                fill="none"
                className={cn(state.strokeClass, 'transition-[stroke-dasharray] duration-500 ease-out')}
                strokeWidth={2.5}
                strokeLinecap="round"
                strokeDasharray={state.dashed ? '2 3' : `${pct} ${100 - pct}`}
                strokeDashoffset={25}
              />
            </svg>
            {state.dotClass && (
              <span className={cn('absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full', state.dotClass)} />
            )}
            {repo?.index_error && (
              <AlertTriangle size={11} className="absolute -right-1 -top-1 text-(--color-error)" />
            )}
            <div className="relative z-(--z-panel) flex h-[52px] flex-col items-center justify-center gap-0.5 px-2 py-1.5">
              <span className="flex w-full items-center justify-center gap-1">
                <GitBranch size={10} className="shrink-0 text-(--color-text-subtle)" />
                <span className="truncate text-[10px] font-medium text-(--color-text)">{node.label}</span>
              </span>
              <span className={cn('text-[13px] font-semibold tabular-nums leading-none', state.textClass)}>{pctLabel}</span>
              <span className="flex items-center gap-1 text-[9px] text-(--color-text-subtle)">
                {repo?.indexing && <Loader2 size={8} className="shrink-0 animate-spin" />}
                {repoCountText(repo)}
              </span>
            </div>
          </div>
        )
      })}

    </div>
  )
}

export interface CrossRepoLinksPanelProps {
  project: CodingProject
  className?: string
}

export function CrossRepoLinksPanel({ project, className }: CrossRepoLinksPanelProps) {
  const queryClient = useQueryClient()
  const isMultiRepo = project.workspaces.length > 1
  const [expanded, setExpanded] = useState(false)
  const [isReindexing, setIsReindexing] = useState(false)

  const edgesQuery = useQuery({
    queryKey: queryKeys.projects.crossRepoEdges(project.id),
    queryFn: () => listCrossRepoEdges(project.id),
    staleTime: 10_000,
  })

  const codeGraphStatusKey = queryKeys.projects.codeGraphStatus(project.id)
  const codeGraphStatusQuery = useQuery({
    queryKey: codeGraphStatusKey,
    queryFn: () => getProjectCodeGraphStatus(project.id),
    staleTime: 5_000,
    refetchInterval: (query) => (query.state.data?.some((r) => r.indexing) ? 800 : false),
  })

  const repos = codeGraphStatusQuery.data ?? []
  const repoIndexing = repos.some((r) => r.indexing)
  const isBusy = repoIndexing || isReindexing
  const indexedCount = repos.filter((r) => r.indexed).length

  // Refresh each repository target, then reload the dynamic graph snapshot.
  const runPipeline = async (full = false) => {
    setIsReindexing(true)
    try {
      await reindexProjectCodeGraph(project.id, { full })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: codeGraphStatusKey }),
        queryClient.invalidateQueries({ queryKey: queryKeys.projects.crossRepoEdges(project.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.projects.codeGraphData(project.id) }),
      ])
    } finally {
      setIsReindexing(false)
    }
  }

  const edges = edgesQuery.data ?? []
  const resolvedCount = edges.filter((e) => e.status === 'resolved').length
  const buttonLabel = isBusy
    ? 'Indexing…'
    : indexedCount > 0
      ? 'Reindex'
      : 'Build index'

  return (
    <div className={cn('flex flex-col gap-2', className)}>
      {isMultiRepo && (
        <RepoGraph project={project} edges={edges} repos={repos} onExpand={() => setExpanded(true)} />
      )}
      <div className="flex items-center justify-between px-1">
        <span className="text-xs font-medium text-(--color-text-muted)">
          {repos.length === 0
            ? 'Loading repos…'
            : !isMultiRepo
              ? `${indexedCount}/${repos.length} repos indexed`
              : edges.length === 0
                ? `${indexedCount}/${repos.length} repos indexed · no cross-repo references yet`
                : `${indexedCount}/${repos.length} repos indexed · ${resolvedCount}/${edges.length} cross-repo references resolved`}
        </span>
        <div className="flex items-center gap-1.5">
          <div className="flex items-center overflow-hidden rounded-md">
            <button
              type="button"
              onClick={() => void runPipeline(false)}
              disabled={isBusy}
              className={cn(
                'flex items-center gap-1 px-2 py-1 text-xs font-medium transition-colors',
                'bg-(--accent-blue) text-white hover:bg-(--accent-blue)/90 disabled:opacity-50',
              )}
            >
              {isBusy ? (
                <Loader2 size={11} className="animate-spin" />
              ) : indexedCount > 0 ? (
                <RefreshCw size={11} />
              ) : (
                <Network size={11} />
              )}
              {buttonLabel}
            </button>
            <DropdownMenu>
              <DropdownMenuTrigger
                disabled={isBusy}
                aria-label="Reindex options"
                className={cn(
                  'flex h-full items-center border-l border-white/25 px-1 py-1 transition-colors',
                  'bg-(--accent-blue) text-white hover:bg-(--accent-blue)/90 disabled:opacity-50',
                )}
              >
                <ChevronDown size={11} />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => void runPipeline(true)}>
                  Force index (full rebuild)
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </div>

      {repoIndexing && (
        <div className="space-y-2 px-1">
          {repos
            .filter((r) => r.indexing)
            .map((r) => {
              const pct = r.index_progress != null ? Math.round(r.index_progress * 100) : null
              const message = r.index_message ?? r.index_phase ?? 'Indexing…'
              return (
                <div key={r.workspace_id} className="flex items-start gap-2">
                  <Loader2 size={12} className="mt-0.5 shrink-0 animate-spin text-(--accent-blue)" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-xs">
                      <span className="truncate font-medium text-(--color-text)">{r.name}</span>
                      <span className="min-w-0 flex-1 truncate text-[10px] text-(--color-text-subtle)">
                        {message}
                      </span>
                      {pct != null && (
                        <span className="shrink-0 font-mono text-[10px] text-(--color-text-muted)">
                          {pct}%
                        </span>
                      )}
                    </div>
                    <div className="mt-1 h-1 overflow-hidden rounded-full bg-(--bg-key)">
                      <div
                        className="h-full rounded-full bg-(--accent-blue) transition-[width] duration-500 ease-out"
                        style={{ width: pct != null ? `${pct}%` : '0%' }}
                      />
                    </div>
                  </div>
                </div>
              )
            })}
        </div>
      )}
      {isMultiRepo && (
        <RepoGraphModal
          open={expanded}
          onOpenChange={setExpanded}
          project={project}
        />
      )}
    </div>
  )
}
