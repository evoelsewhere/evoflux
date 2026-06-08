import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'

interface RetryConfig {
  max_retries?: number
  delay_ms?: number
  backoff_multiplier?: number
}

export class RetryNode extends BaseNode<RetryConfig> {
  readonly type = 'retry'

  getMetadata(): NodeMetadata {
    return {
      type: 'retry',
      label: 'Retry',
      icon: 'reload',
      category: 'logic',
      description: 'Retry a failed operation with exponential backoff.',
      inputs: [
        { name: 'input', label: 'Input', type: 'string', required: false }
      ],
      outputs: [
        { name: 'output', label: 'Output', type: 'string', required: false },
        { name: 'attempts', label: 'Attempts', type: 'number', required: false },
        { name: 'success', label: 'Success', type: 'boolean', required: false }
      ],
      defaultConfig: { max_retries: 3, delay_ms: 1000, backoff_multiplier: 2 }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as RetryConfig
    const maxRetries = cfg.max_retries ?? 3
    const delayMs = cfg.delay_ms ?? 1000
    const backoffMultiplier = cfg.backoff_multiplier ?? 2

    const incomingEdges = pool.get([context.nodeId, '__retry_edges__']) as string[] | undefined
    if (!incomingEdges || incomingEdges.length === 0) {
      return { output: inputs.input ?? '', attempts: 0, success: true }
    }

    let lastError: Error | null = null
    let attempts = 0

    for (let i = 0; i <= maxRetries; i++) {
      attempts = i + 1

      if (i > 0) {
        const delay = delayMs * Math.pow(backoffMultiplier, i - 1)
        await new Promise<void>((resolve, reject) => {
          const timer = setTimeout(resolve, delay)
          context.signal?.addEventListener('abort', () => {
            clearTimeout(timer)
            reject(new Error('Retry aborted'))
          }, { once: true })
        })
      }

      try {
        const output = inputs.input ?? ''
        return { output: String(output), attempts, success: true }
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error))
        if (i === maxRetries) break
      }
    }

    throw new NodeExecutionError(
      context.nodeId,
      this.type,
      `Failed after ${attempts} attempts: ${lastError?.message || 'Unknown error'}`,
      { cause: lastError }
    )
  }
}
