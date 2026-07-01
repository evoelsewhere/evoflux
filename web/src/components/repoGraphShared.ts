/**
 * Shared data helpers for the Graph tab's repo-relationship visualizations —
 * the compact preview in CrossRepoLinksPanel.tsx and the expanded spatial
 * view in RepoGraphModal.tsx both aggregate the same CrossRepoEdge/
 * ProjectRepoStatus data the same way, just render it differently.
 */

import type { CodingProject, CrossRepoEdge, ProjectRepoStatus } from '@/api/types'

export function repoLabel(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

export interface RepoNode {
  workspaceId: string
  path: string
  label: string
  cx: number // 0..100, percentage of container
  cy: number
}

export interface RepoLink {
  srcId: string
  dstId: string
  resolvedCount: number
  unresolvedCount: number
}

// Fixed circular layout — used by the compact preview, where a stable,
// cheap-to-compute arrangement matters more than organic spacing.
export function layoutRepoNodesCircular(workspaces: CodingProject['workspaces']): RepoNode[] {
  const n = workspaces.length
  const radius = n <= 2 ? 30 : n <= 4 ? 36 : 40
  const flatten = n <= 4 ? 0.85 : 0.78
  return workspaces.map((w, i) => {
    // Start at the top (-90deg) and go clockwise so a 2-repo project lays
    // out top/bottom instead of an ambiguous left/right split.
    const angle = (2 * Math.PI * i) / n - Math.PI / 2
    return {
      workspaceId: w.workspace_id,
      path: w.path,
      label: w.display_name || w.name || repoLabel(w.path),
      cx: 50 + radius * Math.cos(angle),
      cy: 50 + radius * Math.sin(angle) * flatten,
    }
  })
}

// Each repo is one node (no per-symbol detail); a link between two repos
// means at least one CrossRepoEdge connects them, aggregated from whatever
// edge list the caller already fetched — no extra request either view.
export function buildRepoLinks(edges: CrossRepoEdge[]): RepoLink[] {
  const byPair = new Map<string, RepoLink>()
  for (const edge of edges) {
    if (!edge.dst_workspace_id || edge.dst_workspace_id === edge.src_workspace_id) continue
    const key = `${edge.src_workspace_id} ${edge.dst_workspace_id}`
    let link = byPair.get(key)
    if (!link) {
      link = { srcId: edge.src_workspace_id, dstId: edge.dst_workspace_id, resolvedCount: 0, unresolvedCount: 0 }
      byPair.set(key, link)
    }
    if (edge.status === 'resolved') link.resolvedCount += 1
    else if (edge.status === 'unresolved') link.unresolvedCount += 1
  }
  return [...byPair.values()].filter((l) => l.resolvedCount > 0 || l.unresolvedCount > 0)
}

// A quadratic bezier between two nodes, offset perpendicular to the
// src→dst midpoint so bidirectional pairs (A→B and B→A) curve apart instead
// of overlapping, and so a fan of edges out of one hub node visually
// separates instead of reading as a wheel of straight chords through center.
export function edgePath(x1: number, y1: number, x2: number, y2: number, hasReverse: boolean) {
  const dx = x2 - x1
  const dy = y2 - y1
  const len = Math.hypot(dx, dy) || 1
  const nx = -dy / len
  const ny = dx / len
  const offset = hasReverse ? 6 : 3
  const cx = (x1 + x2) / 2 + nx * offset
  const cy = (y1 + y2) / 2 + ny * offset
  return {
    d: `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`,
    // The curve's true midpoint (t=0.5), not the straight-line midpoint, so
    // the resolution-% badge sits ON the curve rather than floating off it.
    midX: 0.25 * x1 + 0.5 * cx + 0.25 * x2,
    midY: 0.25 * y1 + 0.5 * cy + 0.25 * y2,
  }
}

// Discrete red/amber/green health bands, reusing already-approved status
// colors app-wide rather than inventing a continuous gradient.
export function edgeBand(resolvedCount: number, unresolvedCount: number): { ratio: number; strokeClass: string; fillClass: string } {
  const total = resolvedCount + unresolvedCount
  const ratio = total > 0 ? resolvedCount / total : 0
  if (ratio === 0) return { ratio, strokeClass: 'stroke-(--color-error)', fillClass: 'fill-(--color-error)' }
  if (ratio < 0.7) return { ratio, strokeClass: 'stroke-(--color-warning)', fillClass: 'fill-(--color-warning)' }
  return { ratio, strokeClass: 'stroke-green-500', fillClass: 'fill-green-500' }
}

export function compactCount(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1).replace(/\.0$/, '')}k` : String(n)
}

export interface RepoRingState {
  strokeClass: string
  textClass: string
  dotClass: string
  dashed: boolean
}

// Indexing state -> ring/dot/text color, kept as static literal class names
// (never string-built at runtime) so Tailwind's build-time scanner can see them.
export function repoRingState(repo: ProjectRepoStatus | undefined): RepoRingState {
  if (repo?.index_error) {
    return { strokeClass: 'stroke-(--color-error)', textClass: 'text-(--color-error)', dotClass: 'bg-(--color-error)', dashed: false }
  }
  if (repo?.indexed) {
    return { strokeClass: 'stroke-green-500', textClass: 'text-green-500', dotClass: 'bg-green-500', dashed: false }
  }
  if (repo?.indexing) {
    return { strokeClass: 'stroke-(--color-warning)', textClass: 'text-(--color-warning)', dotClass: 'bg-(--color-warning) animate-pulse', dashed: false }
  }
  return { strokeClass: 'stroke-(--color-text-subtle)', textClass: 'text-(--color-text-subtle)', dotClass: '', dashed: true }
}

export function repoPct(repo: ProjectRepoStatus | undefined): number {
  if (!repo) return 0
  return repo.indexed ? 100 : Math.round((repo.index_progress ?? 0) * 100)
}

export function repoCountText(repo: ProjectRepoStatus | undefined): string {
  if (!repo) return '—'
  if (repo.index_error) return 'err'
  if (repo.indexed) {
    if (repo.nodes > 0) return `${compactCount(repo.nodes)} syms`
    if (repo.files > 0) return `${compactCount(repo.files)} files`
    return '—'
  }
  if (repo.indexing) return `${compactCount(repo.files)} files`
  return '—'
}
