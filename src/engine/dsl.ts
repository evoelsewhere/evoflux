import { Graph } from './graph'

export interface DSLNode {
  id: string
  type: string
  data: unknown
  position?: { x: number; y: number }
}

export interface DSLEdge {
  id: string
  source: string
  target: string
  sourceHandle?: string
  targetHandle?: string
  label?: string
  condition?: string
  isBackEdge?: boolean
  maxIterations?: number
}

export interface WorkflowDSL {
  version: '2.0'
  name: string
  description: string
  graph: {
    nodes: DSLNode[]
    edges: DSLEdge[]
  }
  config: {
    default_model?: string
    sandbox?: {
      enabled: boolean
      type: 'tempdir' | 'docker'
      allowed_commands?: string[]
    }
    memory?: {
      enabled: boolean
      auto_refine: boolean
      auto_consolidate: boolean
    }
    max_steps?: number
    max_time_seconds?: number
    max_parallel_nodes?: number
  }
  environment_variables?: Array<{
    name: string
    value: string
    is_secret: boolean
  }>
  metadata: {
    created_at: string
    updated_at: string
    tags: string[]
    template?: string
  }
}

export function serializeGraph(graph: Graph, name: string, description: string): WorkflowDSL {
  const now = new Date().toISOString()
  return {
    version: '2.0',
    name,
    description,
    graph: {
      nodes: graph.getNodes().map(n => ({
        id: n.id,
        type: n.type,
        data: n.data,
        position: n.position
      })),
      edges: graph.getEdges().map(e => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle,
        targetHandle: e.targetHandle,
        label: e.label,
        condition: e.condition,
        isBackEdge: e.isBackEdge,
        maxIterations: e.maxIterations
      }))
    },
    config: {},
    environment_variables: [],
    metadata: {
      created_at: now,
      updated_at: now,
      tags: []
    }
  }
}

export function deserializeGraph(dsl: WorkflowDSL): Graph {
  const graph = new Graph()

  for (const node of dsl.graph.nodes) {
    graph.addNode({
      id: node.id,
      type: node.type,
      data: node.data,
      position: node.position
    })
  }

  for (const edge of dsl.graph.edges) {
    graph.addEdge({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle,
      targetHandle: edge.targetHandle,
      label: edge.label,
      condition: edge.condition,
      isBackEdge: edge.isBackEdge,
      maxIterations: edge.maxIterations
    })
  }

  return graph
}

export function validateDSL(data: unknown): data is WorkflowDSL {
  if (typeof data !== 'object' || data === null) return false
  const dsl = data as Record<string, unknown>
  if (dsl.version !== '2.0') return false
  if (typeof dsl.name !== 'string') return false
  if (typeof dsl.graph !== 'object' || dsl.graph === null) return false

  const graph = dsl.graph as Record<string, unknown>
  if (!Array.isArray(graph.nodes)) return false
  if (!Array.isArray(graph.edges)) return false

  for (const node of graph.nodes as Record<string, unknown>[]) {
    if (typeof node.id !== 'string') return false
    if (typeof node.type !== 'string') return false
  }

  for (const edge of graph.edges as Record<string, unknown>[]) {
    if (typeof edge.source !== 'string') return false
    if (typeof edge.target !== 'string') return false
  }

  return true
}
