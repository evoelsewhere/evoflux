import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'

interface VariableAggregatorConfig {
  variables?: string[]
  mode?: 'first' | 'concat' | 'array'
}

export class VariableAggregatorNode extends BaseNode<VariableAggregatorConfig> {
  readonly type = 'variable-aggregator'

  getMetadata(): NodeMetadata {
    return {
      type: 'variable-aggregator',
      label: 'Variable Aggregator',
      icon: 'merge-cells',
      category: 'logic',
      description: 'Merge variables from parallel branches into single output.',
      inputs: [
        { name: 'value_a', label: 'Value A', type: 'string', required: false },
        { name: 'value_b', label: 'Value B', type: 'string', required: false }
      ],
      outputs: [
        { name: 'output', label: 'Merged Output', type: 'string', required: false }
      ],
      defaultConfig: { mode: 'concat' }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    _context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as VariableAggregatorConfig
    const mode = cfg.mode || 'concat'
    const values = Object.values(inputs).filter(v => v !== undefined && v !== null && v !== '')

    if (values.length === 0) return { output: '' }
    if (mode === 'first') return { output: String(values[0]) }
    if (mode === 'array') return { output: JSON.stringify(values) }

    return { output: values.map(v => String(v)).join('\n') }
  }
}
