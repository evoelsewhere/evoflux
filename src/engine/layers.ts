import type { GraphNode } from './graph'
import type { NodeOutput } from './node-factory'

export interface EngineEvent {
  type: string
  nodeId?: string
  output?: NodeOutput
  error?: Error
  timestamp: number
}

export interface GraphEngineLayer {
  name: string
  onGraphStart?(): void | Promise<void>
  onGraphEnd?(result: { completed: number; failed: number }): void | Promise<void>
  onNodeStart?(node: GraphNode): void | Promise<void>
  onNodeEnd?(node: GraphNode, output: NodeOutput): void | Promise<void>
  onNodeError?(node: GraphNode, error: Error): void | Promise<void>
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
      await layer.onGraphStart?.()
    }
  }

  async emitGraphEnd(result: { completed: number; failed: number }): Promise<void> {
    for (const layer of this.layers) {
      await layer.onGraphEnd?.(result)
    }
  }

  async emitNodeStart(node: GraphNode): Promise<void> {
    for (const layer of this.layers) {
      await layer.onNodeStart?.(node)
    }
  }

  async emitNodeEnd(node: GraphNode, output: NodeOutput): Promise<void> {
    for (const layer of this.layers) {
      await layer.onNodeEnd?.(node, output)
    }
  }

  async emitNodeError(node: GraphNode, error: Error): Promise<void> {
    for (const layer of this.layers) {
      await layer.onNodeError?.(node, error)
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

  onNodeStart(node: GraphNode): void {
    this.emit({ type: 'node:start', nodeId: node.id, timestamp: Date.now() })
  }

  onNodeEnd(node: GraphNode, output: NodeOutput): void {
    this.emit({ type: 'node:complete', nodeId: node.id, output, timestamp: Date.now() })
  }

  onNodeError(node: GraphNode, error: Error): void {
    this.emit({ type: 'node:error', nodeId: node.id, error, timestamp: Date.now() })
  }
}
