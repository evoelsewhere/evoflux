import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'

export class EndNode extends BaseNode {
  readonly type = 'end'

  getMetadata(): NodeMetadata {
    return {
      type: 'end',
      label: 'End',
      icon: 'stop-circle',
      category: 'trigger',
      description: 'Workflow terminal node. Collects final outputs.',
      inputs: [{ name: 'output', label: 'Output', type: 'string', required: false }],
      outputs: [],
      defaultConfig: {}
    }
  }

  async run(
    inputs: Record<string, unknown>,
    _config: unknown,
    _pool: VariablePool,
    _context: NodeRunContext
  ): Promise<NodeOutput> {
    return { final_output: inputs.output ?? '' }
  }
}
