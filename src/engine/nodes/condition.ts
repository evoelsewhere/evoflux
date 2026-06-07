import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'

interface ConditionConfig {
  expression?: string
  true_label?: string
  false_label?: string
}

export class ConditionNode extends BaseNode<ConditionConfig> {
  readonly type = 'condition'

  getMetadata(): NodeMetadata {
    return {
      type: 'condition',
      label: 'Condition',
      icon: 'branches',
      category: 'logic',
      description: 'IF/ELSE branching based on boolean expression.',
      inputs: [
        { name: 'value', label: 'Value', type: 'string', required: true }
      ],
      outputs: [
        { name: 'true_branch', label: 'True', type: 'string', required: false },
        { name: 'false_branch', label: 'False', type: 'string', required: false },
        { name: 'result', label: 'Result', type: 'boolean', required: false }
      ],
      defaultConfig: { expression: '', true_label: 'Yes', false_label: 'No' }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as ConditionConfig
    const value = inputs.value
    const expr = cfg.expression || ''

    let result = false

    if (expr) {
      try {
        const fn = new Function('value', `return ${expr}`)
        result = Boolean(fn(value))
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Expression evaluation failed'
        throw new NodeExecutionError(context.nodeId, this.type, `Invalid expression: ${message}`, { cause: error })
      }
    } else {
      result = Boolean(value)
    }

    return {
      true_branch: result ? String(value) : '',
      false_branch: result ? '' : String(value),
      result
    }
  }
}
