import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'
import { resolveTemplate } from '../template-resolver'

interface IterationConfig {
  array_input?: string
  max_iterations?: number
}

export class IterationNode extends BaseNode<IterationConfig> {
  readonly type = 'iteration'

  getMetadata(): NodeMetadata {
    return {
      type: 'iteration',
      label: 'Iteration',
      icon: 'reload',
      category: 'logic',
      description: 'For-each loop over an array. Processes each item.',
      inputs: [
        { name: 'array', label: 'Array', type: 'array', required: true },
        { name: 'item_handler', label: 'Item Handler', type: 'string', required: false }
      ],
      outputs: [
        { name: 'results', label: 'Results', type: 'array', required: false },
        { name: 'current_item', label: 'Last Item', type: 'string', required: false },
        { name: 'index', label: 'Last Index', type: 'number', required: false },
        { name: 'count', label: 'Total Count', type: 'number', required: false }
      ],
      defaultConfig: { max_iterations: 100 }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as IterationConfig
    const maxIterations = cfg.max_iterations || 100

    let array: unknown[]

    if (Array.isArray(inputs.array)) {
      array = inputs.array
    } else if (typeof inputs.array === 'string') {
      try {
        const parsed = JSON.parse(inputs.array)
        if (!Array.isArray(parsed)) {
          throw new NodeExecutionError(context.nodeId, this.type, 'Input is not a valid JSON array')
        }
        array = parsed
      } catch (error) {
        if (error instanceof NodeExecutionError) throw error
        throw new NodeExecutionError(context.nodeId, this.type, 'Failed to parse array input', { cause: error })
      }
    } else {
      throw new NodeExecutionError(context.nodeId, this.type, 'Array input is required')
    }

    const limit = Math.min(array.length, maxIterations)
    const results: unknown[] = []

    const handler = String(inputs.item_handler || '')

    for (let i = 0; i < limit; i++) {
      const item = array[i]
      pool.set([context.nodeId, 'current_item'], item)
      pool.set([context.nodeId, 'index'], i)
      pool.set([context.nodeId, '_item'], item)
      pool.set([context.nodeId, '_index'], i)

      if (handler) {
        const resolved = resolveTemplate(handler, pool)
        results.push(resolved)
      } else {
        results.push(item)
      }
    }

    return {
      results,
      current_item: limit > 0 ? String(array[limit - 1]) : '',
      index: limit - 1,
      count: limit
    }
  }
}
