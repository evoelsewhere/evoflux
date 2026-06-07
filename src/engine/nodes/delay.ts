import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'

interface DelayConfig {
  duration_ms?: number
  duration_seconds?: number
  pass_through?: unknown
}

export class DelayNode extends BaseNode<DelayConfig> {
  readonly type = 'delay'

  getMetadata(): NodeMetadata {
    return {
      type: 'delay',
      label: 'Delay',
      icon: 'clock-circle',
      category: 'logic',
      description: 'Pause workflow execution. Useful for rate limiting, polling, and waiting for async operations.',
      inputs: [
        { name: 'input', label: 'Input (pass-through)', type: 'string', required: false }
      ],
      outputs: [
        { name: 'output', label: 'Pass-through', type: 'string', required: false },
        { name: 'elapsed_ms', label: 'Elapsed (ms)', type: 'number', required: false }
      ],
      defaultConfig: { duration_seconds: 1 }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as DelayConfig
    const durationMs = cfg.duration_ms || (cfg.duration_seconds || 1) * 1000

    if (durationMs < 0) {
      throw new NodeExecutionError(context.nodeId, this.type, 'Duration must be non-negative')
    }

    if (durationMs > 300000) {
      throw new NodeExecutionError(context.nodeId, this.type, 'Duration cannot exceed 5 minutes (300000ms)')
    }

    const start = Date.now()

    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(resolve, durationMs)
      context.signal?.addEventListener('abort', () => {
        clearTimeout(timer)
        reject(new Error('Delay aborted'))
      }, { once: true })
    })

    const elapsed = Date.now() - start

    return {
      output: inputs.input ?? cfg.pass_through ?? '',
      elapsed_ms: elapsed
    }
  }
}
