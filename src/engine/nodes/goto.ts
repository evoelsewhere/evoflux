import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'

interface GotoConfig {
  target_label?: string
  max_iterations?: number
}

export class GotoNode extends BaseNode<GotoConfig> {
  readonly type = 'goto'

  getMetadata(): NodeMetadata {
    return {
      type: 'goto',
      label: 'Goto',
      icon: 'sync',
      category: 'logic',
      description: 'Jump back to a previous node. Creates a loop when connected to an earlier node.',
      inputs: [
        { name: 'input', label: 'Input', type: 'string', required: false }
      ],
      outputs: [
        { name: 'output', label: 'Output', type: 'string', required: false }
      ],
      defaultConfig: { max_iterations: 100 }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    _config: unknown,
    _pool: VariablePool,
    _context: NodeRunContext
  ): Promise<NodeOutput> {
    return { output: inputs.input ?? '' }
  }
}
