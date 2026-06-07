import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'

interface StartConfig {
  variables?: Array<{ name: string; type: string; required?: boolean; default?: unknown }>
}

export class StartNode extends BaseNode<StartConfig> {
  readonly type = 'start'

  getMetadata(): NodeMetadata {
    return {
      type: 'start',
      label: 'Start',
      icon: 'play-circle',
      category: 'trigger',
      description: 'Workflow entry point. Defines input variables.',
      inputs: [],
      outputs: [],
      defaultConfig: { variables: [] }
    }
  }

  async run(
    _inputs: Record<string, unknown>,
    config: unknown,
    pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as StartConfig
    const result: NodeOutput = {}

    for (const v of cfg.variables || []) {
      const value = pool.get([context.nodeId, v.name]) ?? v.default ?? ''
      pool.set([context.nodeId, v.name], value)
      result[v.name] = value
    }

    return result
  }
}
