import type { CodeGraphEdge, CodeGraphNode, CrossRepoEdge, CrossRepoEdgeMethod, CrossRepoEdgeStatus, ProjectRepoStatus } from '@/api/types'

export interface SpatialNode {
  id: string
  workspaceId: string
  kind: string
  label: string
  fullLabel: string
  radius: number
  baseColor: string
  textColor: string
  glowColor: string
  x: number
  y: number
  vx: number
  vy: number
  mass: number
  repo: boolean
  data: CodeGraphNode | ProjectRepoStatus
}

export interface SpatialEdge {
  id: string
  source: string
  target: string
  kind: string
  crossRepo: boolean
  status?: CrossRepoEdgeStatus
  method?: CrossRepoEdgeMethod | null
  data: CodeGraphEdge | CrossRepoEdge
}

export interface SpatialGraphData {
  repos: ProjectRepoStatus[]
  nodes: SpatialNode[]
  edges: SpatialEdge[]
  nodeById: Map<string, SpatialNode>
  edgesByNodeId: Map<string, SpatialEdge[]>
  totalNodeCount: number
  totalEdgeCount: number
  nodeLimitPerRepo: number
  edgeLimitPerRepo: number
}

const REPO_COLORS = [
  { base: '#10b981', glow: '#34d399' },
  { base: '#0ea5e9', glow: '#38bdf8' },
  { base: '#8b5cf6', glow: '#a78bfa' },
  { base: '#f59e0b', glow: '#fbbf24' },
  { base: '#ec4899', glow: '#f472b6' },
  { base: '#14b8a6', glow: '#2dd4bf' },
  { base: '#ef4444', glow: '#f87171' },
  { base: '#6366f1', glow: '#818cf8' },
]

function repoColor(index: number) {
  return REPO_COLORS[index % REPO_COLORS.length]
}

function nodeRadius(kind: string): number {
  switch (kind) {
    case 'file':
    case 'module':
      return 5
    case 'class':
    case 'interface':
      return 4
    case 'function':
    case 'method':
      return 3
    case 'variable':
      return 2
    default:
      return 3
  }
}

function repoLabelFromPath(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

export function buildSpatialData(
  repos: ProjectRepoStatus[],
  codeNodes: CodeGraphNode[],
  codeEdges: CodeGraphEdge[],
  crossEdges: CrossRepoEdge[],
  totalNodeCount: number,
  totalEdgeCount: number,
  nodeLimitPerRepo: number,
  edgeLimitPerRepo: number,
): SpatialGraphData {
  const repoById = new Map(repos.map((r) => [r.workspace_id, r]))
  const repoIndexById = new Map(repos.map((r, i) => [r.workspace_id, i]))
  const repoCount = repos.length
  const repoRadius = Math.max(180, repoCount * 70)

  const spatialNodes: SpatialNode[] = []
  const repoCenters = new Map<string, { x: number; y: number }>()

  repos.forEach((repo, i) => {
    const angle = (2 * Math.PI * i) / Math.max(repoCount, 1) - Math.PI / 2
    const x = repoRadius * Math.cos(angle)
    const y = repoRadius * Math.sin(angle) * 0.85
    repoCenters.set(repo.workspace_id, { x, y })
    const color = repoColor(i)
    spatialNodes.push({
      id: `repo:${repo.workspace_id}`,
      workspaceId: repo.workspace_id,
      kind: 'repo',
      label: repoLabelFromPath(repo.path),
      fullLabel: repo.path,
      radius: repo.indexed ? 24 + Math.min(16, Math.sqrt(repo.nodes) * 0.25) : 18,
      baseColor: repo.index_error ? '#f43f5e' : repo.indexed ? color.base : '#525252',
      textColor: repo.index_error ? '#fda4af' : repo.indexed ? color.glow : '#a3a3a3',
      glowColor: repo.index_error ? '#f43f5e' : repo.indexed ? color.glow : '#525252',
      x,
      y,
      vx: 0,
      vy: 0,
      mass: 8,
      repo: true,
      data: repo,
    })
  })

  const nodesByWorkspace = new Map<string, CodeGraphNode[]>()
  for (const node of codeNodes) {
    const list = nodesByWorkspace.get(node.workspace_id) ?? []
    list.push(node)
    nodesByWorkspace.set(node.workspace_id, list)
  }

  for (const [workspaceId, workspaceNodes] of nodesByWorkspace) {
    const center = repoCenters.get(workspaceId)
    if (!center) continue
    const repo = repoById.get(workspaceId)
    if (!repo?.indexed) continue
    const colorIndex = repoIndexById.get(workspaceId) ?? 0
    const color = repoColor(colorIndex)

    workspaceNodes.forEach((node, i) => {
      const ring = 60 + (i % 4) * 35
      const angle = (2 * Math.PI * i) / Math.max(workspaceNodes.length, 1) + (colorIndex * 0.7)
      const r = nodeRadius(node.kind)
      spatialNodes.push({
        id: node.id,
        workspaceId,
        kind: node.kind,
        label: node.name,
        fullLabel: node.qualified_name,
        radius: r,
        baseColor: color.base,
        textColor: '#e2e8f0',
        glowColor: color.glow,
        x: center.x + ring * Math.cos(angle),
        y: center.y + ring * Math.sin(angle) * 0.85,
        vx: 0,
        vy: 0,
        mass: Math.max(1, r * 0.4),
        repo: false,
        data: node,
      })
    })
  }

  const nodeIds = new Set(spatialNodes.map((n) => n.id))
  const spatialEdges: SpatialEdge[] = []

  for (const edge of codeEdges) {
    if (!nodeIds.has(edge.src_id) || !nodeIds.has(edge.dst_id)) continue
    spatialEdges.push({
      id: `intra:${edge.id}`,
      source: edge.src_id,
      target: edge.dst_id,
      kind: edge.kind,
      crossRepo: false,
      data: edge,
    })
  }

  for (const edge of crossEdges) {
    const srcNode = edge.src_node_id
    const srcFallback = `repo:${edge.src_workspace_id}`
    const dstNode = edge.dst_node_id
    const dstFallback = edge.dst_workspace_id ? `repo:${edge.dst_workspace_id}` : null

    const sourceId = (srcNode && nodeIds.has(srcNode)) ? srcNode : (nodeIds.has(srcFallback) ? srcFallback : null)
    const targetId = (dstNode && nodeIds.has(dstNode)) ? dstNode : (dstFallback && nodeIds.has(dstFallback) ? dstFallback : null)

    if (!sourceId || !targetId || sourceId === targetId) continue
    spatialEdges.push({
      id: `cross:${edge.id}`,
      source: sourceId,
      target: targetId,
      kind: edge.kind,
      crossRepo: true,
      status: edge.status,
      method: edge.method,
      data: edge,
    })
  }

  const nodeById = new Map<string, SpatialNode>()
  for (const n of spatialNodes) nodeById.set(n.id, n)

  const edgesByNodeId = new Map<string, SpatialEdge[]>()
  for (const edge of spatialEdges) {
    const srcList = edgesByNodeId.get(edge.source) ?? []
    srcList.push(edge)
    edgesByNodeId.set(edge.source, srcList)
    const dstList = edgesByNodeId.get(edge.target) ?? []
    dstList.push(edge)
    edgesByNodeId.set(edge.target, dstList)
  }

  return {
    repos,
    nodes: spatialNodes,
    edges: spatialEdges,
    nodeById,
    edgesByNodeId,
    totalNodeCount,
    totalEdgeCount,
    nodeLimitPerRepo,
    edgeLimitPerRepo,
  }
}
