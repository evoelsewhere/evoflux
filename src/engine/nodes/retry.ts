import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'

interface RetryConfig {
  max_retries?: number
  delay_ms?: number
  backoff_multiplier?: number
  validation?: string
}

export class RetryNode extends BaseNode<RetryConfig> {
  readonly type = 'retry'

  getMetadata(): NodeMetadata {
    return {
      type: 'retry',
      label: 'Retry',
      icon: 'reload',
      category: 'logic',
      description: 'Retry gate: validates input and outputs to retry or success handle. Connect retry handle to a back-edge.',
      inputs: [
        { name: 'input', label: 'Input', type: 'string', required: true }
      ],
      outputs: [
        { name: 'success', label: 'Success', type: 'string', required: false },
        { name: 'retry', label: 'Retry', type: 'string', required: false },
        { name: 'error', label: 'Error', type: 'string', required: false },
        { name: 'attempts', label: 'Attempts', type: 'number', required: false }
      ],
      defaultConfig: { max_retries: 3, delay_ms: 1000, backoff_multiplier: 2, validation: '' }
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
    const validation = cfg.validation || ''

    const attempts = (pool.get([context.nodeId, '__attempts__']) as number || 0) + 1
    pool.set([context.nodeId, '__attempts__'], attempts)

    const input = inputs.input

    let isValid = true

    if (validation) {
      try {
        const fn = new Function('input', 'value', 'attempts', `return ${validation}`)
        isValid = Boolean(fn(input, input, attempts))
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Validation expression failed'
        throw new NodeExecutionError(context.nodeId, this.type, `Invalid validation expression: ${message}`, { cause: error })
      }
    }

    if (isValid) {
      pool.set([context.nodeId, '__attempts__'], 0)
      return {
        success: String(input),
        retry: '',
        error: '',
        attempts
      }
    }

    if (attempts >= maxRetries) {
      pool.set([context.nodeId, '__attempts__'], 0)
      return {
        success: '',
        retry: '',
        error: `Failed after ${attempts} attempts: validation failed`,
        attempts
      }
    }

    if (delayMs > 0) {
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(resolve, Math.min(delayMs * Math.pow(backoffMultiplier, attempts - 1), 30000))
        context.signal?.addEventListener('abort', () => {
          clearTimeout(timer)
          reject(new Error('Retry aborted'))
        }, { once: true })
      })
    }

    return {
      success: '',
      retry: String(input),
      error: '',
      attempts
    }
  }
}
