import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'

interface VariableAssignerConfig {
  variable_name?: string
  value?: unknown
}

export class VariableAssignerNode extends BaseNode<VariableAssignerConfig> {
  readonly type = 'variable-assigner'

  getMetadata(): NodeMetadata {
    return {
      type: 'variable-assigner',
      label: 'Variable Assigner',
      icon: 'edit',
      category: 'logic',
      description: 'Set or overwrite a variable value at runtime.',
      inputs: [
        { name: 'value', label: 'Value', type: 'string', required: true }
      ],
      outputs: [
        { name: 'output', label: 'Output', type: 'string', required: false }
      ],
      defaultConfig: { variable_name: '', value: '' }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as VariableAssignerConfig
    const value = inputs.value ?? cfg.value ?? ''
    const varName = cfg.variable_name || 'output'

    pool.set([context.nodeId, varName], value)
    return { output: value }
  }
}
