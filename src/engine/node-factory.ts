import type { VariablePool } from './variable-pool'

export type PortType = 'string' | 'number' | 'boolean' | 'object' | 'array' | 'file'

export interface PortDefinition {
  name: string
  label: string
  type: PortType
  required: boolean
}

export interface NodeMetadata {
  type: string
  label: string
  icon: string
  category: 'ai' | 'logic' | 'tools' | 'agent' | 'trigger'
  description: string
  inputs: readonly PortDefinition[]
  outputs: readonly PortDefinition[]
  defaultConfig: unknown
}

export interface NodeOutput {
  [key: string]: unknown
}

export type NodeStatus = 'idle' | 'running' | 'completed' | 'error'

export interface NodeRunContext {
  nodeId: string
  signal?: AbortSignal
}

export abstract class BaseNode<_TConfig = unknown> {
  abstract readonly type: string

  abstract getMetadata(): NodeMetadata

  abstract run(
    inputs: Record<string, unknown>,
    config: unknown,
    pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput>

  validateInputs(inputs: Record<string, unknown>, metadata: NodeMetadata): void {
    for (const port of metadata.inputs) {
      if (port.required && (inputs[port.name] === undefined || inputs[port.name] === null)) {
        throw new Error(`Required input '${port.name}' (${port.label}) is missing`)
      }
    }
  }
}

const nodeRegistry = new Map<string, { new (): BaseNode }>()

export function RegisterNode(type: string) {
  return function (target: { new (): BaseNode }) {
    nodeRegistry.set(type, target)
  }
}

export class NodeFactory {
  static create(type: string): BaseNode {
    const NodeClass = nodeRegistry.get(type)
    if (!NodeClass) {
      throw new Error(`Unknown node type: '${type}'. Registered types: ${Array.from(nodeRegistry.keys()).join(', ')}`)
    }
    return new NodeClass()
  }

  static has(type: string): boolean {
    return nodeRegistry.has(type)
  }

  static getRegisteredTypes(): string[] {
    return Array.from(nodeRegistry.keys())
  }

  static getMetadata(type: string): NodeMetadata {
    return NodeFactory.create(type).getMetadata()
  }

  static getAllMetadata(): NodeMetadata[] {
    return Array.from(nodeRegistry.keys()).map(type => NodeFactory.getMetadata(type))
  }
}
