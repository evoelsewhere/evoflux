import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'

interface LoopConfig {
  condition?: string
  transform?: string
  max_iterations?: number
}

export class LoopNode extends BaseNode<LoopConfig> {
  readonly type = 'loop'

  getMetadata(): NodeMetadata {
    return {
      type: 'loop',
      label: 'Loop',
      icon: 'sync',
      category: 'logic',
      description: 'While loop with condition. Max iterations safety limit.',
      inputs: [
        { name: 'value', label: 'Value', type: 'string', required: true }
      ],
      outputs: [
        { name: 'output', label: 'Final Output', type: 'string', required: false },
        { name: 'iterations', label: 'Iterations', type: 'number', required: false }
      ],
      defaultConfig: { condition: '', transform: '', max_iterations: 100 }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as LoopConfig
    const maxIterations = cfg.max_iterations || 100
    const condition = cfg.condition || ''
    const transform = cfg.transform || ''

    if (!condition) {
      return { output: inputs.value, iterations: 0 }
    }

    let iterations = 0
    let currentValue = inputs.value

    while (iterations < maxIterations) {
      let result = false
      try {
        const fn = new Function('value', 'iteration', `return ${condition}`)
        result = Boolean(fn(currentValue, iterations))
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Condition evaluation failed'
        throw new NodeExecutionError(context.nodeId, this.type, `Invalid condition: ${message}`, { cause: error })
      }

      if (!result) break

      if (transform) {
        try {
          const fn = new Function('value', 'iteration', `return ${transform}`)
          currentValue = fn(currentValue, iterations)
        } catch (error) {
          const message = error instanceof Error ? error.message : 'Transform evaluation failed'
          throw new NodeExecutionError(context.nodeId, this.type, `Invalid transform: ${message}`, { cause: error })
        }
      }

      iterations++
    }

    if (iterations >= maxIterations) {
      throw new NodeExecutionError(context.nodeId, this.type, `Loop exceeded max iterations: ${maxIterations}`)
    }

    return { output: currentValue, iterations }
  }
}
