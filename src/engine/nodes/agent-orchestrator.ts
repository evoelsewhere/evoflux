import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'

interface OrchestratorConfig {
  task?: string
  expected_output?: string
  output_handles?: string[]
  provider_id?: string
  model?: string
}

export class AgentOrchestratorNode extends BaseNode<OrchestratorConfig> {
  readonly type = 'agent-orchestrator'

  getMetadata(): NodeMetadata {
    return {
      type: 'agent-orchestrator',
      label: 'Agent Orchestrator',
      icon: 'team',
      category: 'agent',
      description: 'Dispatch a task to multiple AI Agent nodes via output handles. Connect each handle to a separate AI Agent.',
      inputs: [
        { name: 'task', label: 'Task', type: 'string', required: false },
        { name: 'context', label: 'Context', type: 'string', required: false }
      ],
      outputs: [
        { name: 'output', label: 'Output', type: 'string', required: false }
      ],
      defaultConfig: {
        task: '',
        expected_output: '',
        output_handles: ['implementer', 'reviewer'],
        provider_id: '',
        model: ''
      }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as OrchestratorConfig
    const task = String(cfg.task || inputs.task || '')
    const contextStr = inputs.context ? String(inputs.context) : ''
    const handles = cfg.output_handles || []

    if (!task) {
      throw new NodeExecutionError(context.nodeId, this.type, 'Task is required')
    }

    if (handles.length === 0) {
      throw new NodeExecutionError(context.nodeId, this.type, 'At least one output handle is required. Configure output handles in node settings.')
    }

    const fullTask = contextStr ? `${task}\n\nContext:\n${contextStr}` : task
    const result: Record<string, string> = {}

    for (const handle of handles) {
      result[handle] = fullTask
    }

    result.output = `Dispatched task to ${handles.length} agents: ${handles.join(', ')}`

    return result
  }
}
