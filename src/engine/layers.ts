import type { GraphNode } from './graph'
import type { NodeOutput } from './node-factory'

export interface EngineEvent {
  type: string
  nodeId?: string
  edgeId?: string
  output?: NodeOutput
  error?: Error
  iteration?: number
  timestamp: number
}

export interface GraphEngineLayer {
  name: string
  onGraphStart?(): void | Promise<void>
  onGraphEnd?(result: { completed: number; failed: number }): void | Promise<void>
  onNodeStart?(node: GraphNode, iteration?: number): void | Promise<void>
  onNodeEnd?(node: GraphNode, output: NodeOutput, iteration?: number): void | Promise<void>
  onNodeError?(node: GraphNode, error: Error): void | Promise<void>
  onEdgeActivate?(edgeId: string, source: string, target: string): void | Promise<void>
  onEdgeSkip?(edgeId: string, source: string, target: string): void | Promise<void>
}

export class LayerManager {
  private layers: GraphEngineLayer[] = []

  add(layer: GraphEngineLayer): void {
    this.layers.push(layer)
  }

  remove(name: string): void {
    this.layers = this.layers.filter(l => l.name !== name)
  }

  async emitGraphStart(): Promise<void> {
    for (const layer of this.layers) {
      try { await layer.onGraphStart?.() } catch (e) { console.warn(`[Layer:${layer.name}] onGraphStart error:`, e) }
    }
  }

  async emitGraphEnd(result: { completed: number; failed: number }): Promise<void> {
    for (const layer of this.layers) {
      try { await layer.onGraphEnd?.(result) } catch (e) { console.warn(`[Layer:${layer.name}] onGraphEnd error:`, e) }
    }
  }

  async emitNodeStart(node: GraphNode, iteration?: number): Promise<void> {
    for (const layer of this.layers) {
      try { await layer.onNodeStart?.(node, iteration) } catch (e) { console.warn(`[Layer:${layer.name}] onNodeStart error:`, e) }
    }
  }

  async emitNodeEnd(node: GraphNode, output: NodeOutput, iteration?: number): Promise<void> {
    for (const layer of this.layers) {
      try { await layer.onNodeEnd?.(node, output, iteration) } catch (e) { console.warn(`[Layer:${layer.name}] onNodeEnd error:`, e) }
    }
  }

  async emitNodeError(node: GraphNode, error: Error): Promise<void> {
    for (const layer of this.layers) {
      try { await layer.onNodeError?.(node, error) } catch (e) { console.warn(`[Layer:${layer.name}] onNodeError error:`, e) }
    }
  }

  async emitEdgeActivate(edgeId: string, source: string, target: string): Promise<void> {
    for (const layer of this.layers) {
      try { await layer.onEdgeActivate?.(edgeId, source, target) } catch (e) { console.warn(`[Layer:${layer.name}] onEdgeActivate error:`, e) }
    }
  }

  async emitEdgeSkip(edgeId: string, source: string, target: string): Promise<void> {
    for (const layer of this.layers) {
      try { await layer.onEdgeSkip?.(edgeId, source, target) } catch (e) { console.warn(`[Layer:${layer.name}] onEdgeSkip error:`, e) }
    }
  }
}

export class UILayer implements GraphEngineLayer {
  name = 'ui'
  private emit: (event: EngineEvent) => void

  constructor(emit: (event: EngineEvent) => void) {
    this.emit = emit
  }

  onGraphStart(): void {
    this.emit({ type: 'graph:start', timestamp: Date.now() })
  }

  onGraphEnd(result: { completed: number; failed: number }): void {
    this.emit({ type: 'graph:end', timestamp: Date.now(), ...result })
  }

  onNodeStart(node: GraphNode, iteration?: number): void {
    this.emit({ type: 'node:start', nodeId: node.id, iteration, timestamp: Date.now() })
  }

  onNodeEnd(node: GraphNode, output: NodeOutput, iteration?: number): void {
    this.emit({ type: 'node:complete', nodeId: node.id, output, iteration, timestamp: Date.now() })
  }

  onNodeError(node: GraphNode, error: Error): void {
    this.emit({ type: 'node:error', nodeId: node.id, error, timestamp: Date.now() })
  }

  onEdgeActivate(edgeId: string, source: string, target: string): void {
    this.emit({ type: 'edge:activate', edgeId, nodeId: source, timestamp: Date.now() })
  }

  onEdgeSkip(edgeId: string, source: string, target: string): void {
    this.emit({ type: 'edge:skip', edgeId, nodeId: source, timestamp: Date.now() })
  }
}
