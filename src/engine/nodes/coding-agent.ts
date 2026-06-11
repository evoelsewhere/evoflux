import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'
import { runAgent, type AgentEvent } from '../agent/agent-loop'

interface CodingAgentConfig {
  codebase_path?: string
  max_iterations?: number
  provider_id?: string
  model?: string
  task?: string
  context?: string
}

export class CodingAgentNode extends BaseNode<CodingAgentConfig> {
  readonly type = 'coding-agent'

  getMetadata(): NodeMetadata {
    return {
      type: 'coding-agent',
      label: 'Coding Agent',
      icon: 'code',
      category: 'tools',
      description: 'AI coding agent that reads, writes, edits files and runs commands to complete tasks.',
      inputs: [
        { name: 'task', label: 'Task', type: 'string', required: true },
        { name: 'context', label: 'Context', type: 'string', required: false }
      ],
      outputs: [
        { name: 'summary', label: 'Summary', type: 'string', required: false },
        { name: 'files_changed', label: 'Files Changed', type: 'array', required: false },
        { name: 'needs_more_info', label: 'Needs More Info', type: 'string', required: false },
        { name: 'success', label: 'Success', type: 'boolean', required: false }
      ],
      defaultConfig: {
        codebase_path: '',
        max_iterations: 20,
        provider_id: '',
        model: ''
      }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as CodingAgentConfig
    const task = String(inputs.task || cfg.task || '')
    const ctx = inputs.context ? String(inputs.context) : (cfg.context || '')
    const codebasePath = String(cfg.codebase_path || '')

    if (!task) throw new NodeExecutionError(context.nodeId, this.type, 'Task is required')
    if (!codebasePath) throw new NodeExecutionError(context.nodeId, this.type, 'Codebase path is required. Set it in node config.')

    const globalChat = (globalThis as any).__evolux_ai_chat as
      | ((messages: Array<{ role: string; content: string }>, opts?: { model?: string; provider?: string }) => Promise<string>)
      | undefined

    if (!globalChat) throw new NodeExecutionError(context.nodeId, this.type, 'AI chat not available')

    const events: AgentEvent[] = []
    let summary = ''
    let filesChanged: string[] = []
    let needsInfo = ''
    let success = false

    try {
      for await (const event of runAgent({
        task,
        codebasePath,
        context: ctx || undefined,
        maxIterations: cfg.max_iterations || 20,
        provider: cfg.provider_id,
        model: cfg.model
      }, globalChat)) {
        events.push(event)

        if (event.type === 'complete') {
          summary = event.content
          filesChanged = event.filesChanged || []
          success = true
        }
        if (event.type === 'needs_info') {
          needsInfo = event.content
        }
        if (event.type === 'error') {
          summary = event.content
          success = false
        }
      }
    } catch (error) {
      throw new NodeExecutionError(context.nodeId, this.type, error instanceof Error ? error.message : String(error), { cause: error })
    }

    const log = events
      .filter(e => e.type === 'tool_call' || e.type === 'tool_result' || e.type === 'complete' || e.type === 'error')
      .map(e => `[${e.type}] ${e.content?.substring(0, 100)}`)
      .join('\n')

    return {
      summary: summary || 'Agent completed',
      files_changed: filesChanged,
      needs_more_info: needsInfo,
      success,
      log,
      events: events.map(e => ({ type: e.type, content: e.content?.substring(0, 200), tool: e.tool }))
    }
  }
}
