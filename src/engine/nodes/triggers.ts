import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'

interface ManualTriggerConfig {
  variables?: Array<{ name: string; type: string; required?: boolean; default?: unknown }>
}

export class ManualTriggerNode extends BaseNode<ManualTriggerConfig> {
  readonly type = 'manual-trigger'

  getMetadata(): NodeMetadata {
    return {
      type: 'manual-trigger',
      label: 'Manual Trigger',
      icon: 'play-circle',
      category: 'trigger',
      description: 'User-initiated workflow execution with input form.',
      inputs: [],
      outputs: [],
      defaultConfig: { variables: [] }
    }
  }

  async run(
    _inputs: Record<string, unknown>,
    config: unknown,
    pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as ManualTriggerConfig
    const result: NodeOutput = {}
    for (const v of cfg.variables || []) {
      const value = pool.get([context.nodeId, v.name]) ?? v.default ?? ''
      pool.set([context.nodeId, v.name], value)
      result[v.name] = value
    }
    return result
  }
}

export class WebhookTriggerNode extends BaseNode {
  readonly type = 'webhook-trigger'

  getMetadata(): NodeMetadata {
    return {
      type: 'webhook-trigger',
      label: 'Webhook Trigger',
      icon: 'global',
      category: 'trigger',
      description: 'HTTP webhook endpoint. POST body as input.',
      inputs: [],
      outputs: [
        { name: 'body', label: 'Request Body', type: 'string', required: false },
        { name: 'headers', label: 'Headers', type: 'object', required: false },
        { name: 'method', label: 'Method', type: 'string', required: false }
      ],
      defaultConfig: { path: '/webhook', method: 'POST' }
    }
  }

  async run(
    _inputs: Record<string, unknown>,
    _config: unknown,
    _pool: VariablePool,
    _context: NodeRunContext
  ): Promise<NodeOutput> {
    return { body: '', headers: {}, method: 'POST' }
  }
}

export class ScheduleTriggerNode extends BaseNode {
  readonly type = 'schedule-trigger'

  getMetadata(): NodeMetadata {
    return {
      type: 'schedule-trigger',
      label: 'Schedule Trigger',
      icon: 'clock-circle',
      category: 'trigger',
      description: 'Cron-based scheduled workflow execution.',
      inputs: [],
      outputs: [
        { name: 'timestamp', label: 'Timestamp', type: 'string', required: false }
      ],
      defaultConfig: { cron: '0 * * * *' }
    }
  }

  async run(
    _inputs: Record<string, unknown>,
    _config: unknown,
    _pool: VariablePool,
    _context: NodeRunContext
  ): Promise<NodeOutput> {
    return { timestamp: new Date().toISOString() }
  }
}
