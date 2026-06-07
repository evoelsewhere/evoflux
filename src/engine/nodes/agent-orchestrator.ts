import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError, AgentError } from '../errors'
import { type AgentDefinition, createAgent } from '../agent/agent-definition'
import { createTeamState } from '../agent/team-state'
import { runSequential } from '../agent/process-sequential'
import { runHierarchical, type HierarchicalConfig } from '../agent/process-hierarchical'
import { registerBuiltinTools } from '../agent/builtin-tools'

let toolsRegistered = false

interface OrchestratorConfig {
  task?: string
  expected_output?: string
  process?: 'sequential' | 'hierarchical'
  agents?: AgentDefinition[]
  planning?: boolean
  max_rounds?: number
  max_stalls?: number
  manager_model?: string
  manager_provider?: 'openai' | 'ollama'
}

export class AgentOrchestratorNode extends BaseNode<OrchestratorConfig> {
  readonly type = 'agent-orchestrator'

  getMetadata(): NodeMetadata {
    return {
      type: 'agent-orchestrator',
      label: 'Agent Orchestrator',
      icon: 'team',
      category: 'agent',
      description: 'Manage a team of agents. Sequential or hierarchical process.',
      inputs: [
        { name: 'task', label: 'Task', type: 'string', required: true },
        { name: 'context', label: 'Context', type: 'string', required: false }
      ],
      outputs: [
        { name: 'output', label: 'Output', type: 'string', required: false },
        { name: 'results', label: 'Results', type: 'array', required: false },
        { name: 'rounds', label: 'Rounds', type: 'number', required: false }
      ],
      defaultConfig: {
        process: 'sequential',
        planning: false,
        max_rounds: 15,
        max_stalls: 3,
        manager_model: 'gpt-4o',
        manager_provider: 'openai',
        agents: []
      }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    if (!toolsRegistered) {
      registerBuiltinTools()
      toolsRegistered = true
    }

    const cfg = config as OrchestratorConfig
    const task = String(inputs.task || cfg.task || '')
    const contextStr = inputs.context ? String(inputs.context) : ''
    const processType = cfg.process || 'sequential'
    const expectedOutput = String(cfg.expected_output || 'Complete the task')

    if (!task) {
      throw new NodeExecutionError(context.nodeId, this.type, 'Task is required')
    }

    const agents = (cfg.agents || []).map(a => createAgent(a))
    if (agents.length === 0) {
      throw new NodeExecutionError(context.nodeId, this.type, 'At least one agent is required')
    }

    const fullTask = contextStr ? `${task}\n\nContext:\n${contextStr}` : task
    const state = createTeamState(fullTask, expectedOutput)

    try {
      if (processType === 'hierarchical') {
        const hierConfig: HierarchicalConfig = {
          managerModel: cfg.manager_model || 'gpt-4o',
          managerProvider: cfg.manager_provider || 'openai',
          maxRounds: cfg.max_rounds || 15,
          maxStalls: cfg.max_stalls || 3,
          planning: cfg.planning || false
        }
        const result = await runHierarchical(agents, state, hierConfig, context.signal)
        return {
          output: result.output,
          results: result.results,
          rounds: result.rounds
        }
      }

      const result = await runSequential(agents, state, context.signal)
      return {
        output: result.output,
        results: result.results,
        rounds: result.results.length
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Orchestrator failed'
      throw new AgentError(`Orchestrator error: ${message}`, { cause: error })
    }
  }
}
