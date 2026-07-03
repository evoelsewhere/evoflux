import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'

export class GotoNode extends BaseNode {
  readonly type = 'goto'

  getMetadata(): NodeMetadata {
    return {
      type: 'goto',
      label: 'Goto',
      icon: 'sync',
      category: 'logic',
      description: 'Pass-through node. Connect its output to an earlier node via a back-edge to create a loop.',
      inputs: [
        { name: 'input', label: 'Input', type: 'string', required: false }
      ],
      outputs: [
        { name: 'output', label: 'Output', type: 'string', required: false }
      ],
      defaultConfig: {}
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
