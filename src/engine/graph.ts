import { CycleDetectedError, GraphError } from './errors'

export interface GraphNode<T = unknown> {
  id: string
  type: string
  data: T
  position?: { x: number; y: number }
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  sourceHandle?: string
  targetHandle?: string
  label?: string
}

export interface GraphNodeInput {
  id?: string
  type: string
  data: unknown
  position?: { x: number; y: number }
}

export interface GraphEdgeInput {
  id?: string
  source: string
  target: string
  sourceHandle?: string
  targetHandle?: string
  label?: string
}

export class Graph<T = unknown> {
  private nodes = new Map<string, GraphNode<T>>()
  private outgoing = new Map<string, Set<string>>()
  private incoming = new Map<string, Set<string>>()
  private edgesList: GraphEdge[] = []

  addNode(node: GraphNode<T>): void {
    if (this.nodes.has(node.id)) {
      throw new GraphError(`Node '${node.id}' already exists`)
    }
    this.nodes.set(node.id, node)
    if (!this.outgoing.has(node.id)) this.outgoing.set(node.id, new Set())
    if (!this.incoming.has(node.id)) this.incoming.set(node.id, new Set())
  }

  removeNode(nodeId: string): void {
    if (!this.nodes.has(nodeId)) return

    const outgoing = this.outgoing.get(nodeId) || new Set()
    const incoming = this.incoming.get(nodeId) || new Set()

    for (const target of outgoing) {
      this.incoming.get(target)?.delete(nodeId)
    }
    for (const source of incoming) {
      this.outgoing.get(source)?.delete(nodeId)
    }

    this.edgesList = this.edgesList.filter(e => e.source !== nodeId && e.target !== nodeId)
    this.nodes.delete(nodeId)
    this.outgoing.delete(nodeId)
    this.incoming.delete(nodeId)
  }

  addEdge(edge: GraphEdge): void {
    if (!this.nodes.has(edge.source)) {
      throw new GraphError(`Source node '${edge.source}' not found`)
    }
    if (!this.nodes.has(edge.target)) {
      throw new GraphError(`Target node '${edge.target}' not found`)
    }

    this.outgoing.get(edge.source)!.add(edge.target)
    this.incoming.get(edge.target)!.add(edge.source)
    this.edgesList.push(edge)
  }

  removeEdge(edgeId: string): void {
    const edge = this.edgesList.find(e => e.id === edgeId)
    if (!edge) return

    this.outgoing.get(edge.source)?.delete(edge.target)
    this.incoming.get(edge.target)?.delete(edge.source)
    this.edgesList = this.edgesList.filter(e => e.id !== edgeId)
  }

  getNode(nodeId: string): GraphNode<T> | undefined {
    return this.nodes.get(nodeId)
  }

  getNodes(): GraphNode<T>[] {
    return Array.from(this.nodes.values())
  }

  getEdges(): GraphEdge[] {
    return [...this.edgesList]
  }

  getOutgoing(nodeId: string): string[] {
    return Array.from(this.outgoing.get(nodeId) || [])
  }

  getIncoming(nodeId: string): string[] {
    return Array.from(this.incoming.get(nodeId) || [])
  }

  getRoots(): string[] {
    const roots: string[] = []
    for (const [nodeId, deps] of this.incoming) {
      if (deps.size === 0) roots.push(nodeId)
    }
    return roots
  }

  getLeaves(): string[] {
    const leaves: string[] = []
    for (const [nodeId, deps] of this.outgoing) {
      if (deps.size === 0) leaves.push(nodeId)
    }
    return leaves
  }

  get size(): number {
    return this.nodes.size
  }

  hasNode(nodeId: string): boolean {
    return this.nodes.has(nodeId)
  }

  topologicalSort(): string[] {
    const inDegree = new Map<string, number>()
    const adjacency = new Map<string, string[]>()

    for (const nodeId of this.nodes.keys()) {
      inDegree.set(nodeId, 0)
      adjacency.set(nodeId, [])
    }

    for (const edge of this.edgesList) {
      adjacency.get(edge.source)!.push(edge.target)
      inDegree.set(edge.target, (inDegree.get(edge.target) || 0) + 1)
    }

    const queue: string[] = []
    for (const [nodeId, degree] of inDegree) {
      if (degree === 0) queue.push(nodeId)
    }

    const sorted: string[] = []
    while (queue.length > 0) {
      const current = queue.shift()!
      sorted.push(current)

      for (const neighbor of adjacency.get(current) || []) {
        const newDegree = (inDegree.get(neighbor) || 1) - 1
        inDegree.set(neighbor, newDegree)
        if (newDegree === 0) queue.push(neighbor)
      }
    }

    if (sorted.length !== this.nodes.size) {
      const visited = new Set(sorted)
      const cycleNodes: string[] = []
      for (const nodeId of this.nodes.keys()) {
        if (!visited.has(nodeId)) cycleNodes.push(nodeId)
      }
      throw new CycleDetectedError(cycleNodes)
    }

    return sorted
  }

  getParallelGroups(): string[][] {
    const sorted = this.topologicalSort()
    const levels = new Map<string, number>()

    for (const nodeId of sorted) {
      const deps = this.incoming.get(nodeId) || new Set()
      if (deps.size === 0) {
        levels.set(nodeId, 0)
      } else {
        let maxLevel = 0
        for (const dep of deps) {
          maxLevel = Math.max(maxLevel, levels.get(dep) || 0)
        }
        levels.set(nodeId, maxLevel + 1)
      }
    }

    const groups = new Map<number, string[]>()
    for (const [nodeId, level] of levels) {
      if (!groups.has(level)) groups.set(level, [])
      groups.get(level)!.push(nodeId)
    }

    const result: string[][] = []
    const sortedLevels = Array.from(groups.keys()).sort((a, b) => a - b)
    for (const level of sortedLevels) {
      result.push(groups.get(level)!)
    }

    return result
  }

  toJSON(): { nodes: GraphNode<T>[]; edges: GraphEdge[] } {
    return {
      nodes: this.getNodes(),
      edges: this.getEdges()
    }
  }
}
