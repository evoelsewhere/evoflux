import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError, AgentError } from '../errors'
import { parseAgentOutput, buildAgentSystemPrompt, buildToolResultPrompt, type ParsedAction } from '../agent/parser'
import { getTool, getAllTools, checkPermission, type AgentTool, type ToolPermission, type ToolContext } from '../agent/tools'
import { registerBuiltinTools } from '../agent/builtin-tools'

let toolsRegistered = false

interface ReActAgentConfig {
  model?: string
  provider?: 'openai' | 'ollama'
  system_prompt?: string
  tools?: string[]
  max_iterations?: number
  max_time_seconds?: number
  early_stop_condition?: string
  use_memory?: boolean
  permissions?: ToolPermission
}

export interface AgentEvent {
  type: 'thought' | 'action' | 'observation' | 'finish' | 'error'
  iteration: number
  content: string
  toolName?: string
  toolArgs?: Record<string, unknown>
}

export class ReActAgentNode extends BaseNode<ReActAgentConfig> {
  readonly type = 'react-agent'

  getMetadata(): NodeMetadata {
    return {
      type: 'react-agent',
      label: 'ReAct Agent',
      icon: 'robot',
      category: 'agent',
      description: 'Thought → Action → Observation loop. Multi-step reasoning with tools.',
      inputs: [
        { name: 'task', label: 'Task', type: 'string', required: true },
        { name: 'context', label: 'Context', type: 'string', required: false }
      ],
      outputs: [
        { name: 'output', label: 'Output', type: 'string', required: false },
        { name: 'iterations', label: 'Iterations', type: 'number', required: false },
        { name: 'thoughts', label: 'Thoughts', type: 'array', required: false }
      ],
      defaultConfig: {
        model: 'gpt-4o',
        provider: 'openai',
        max_iterations: 25,
        max_time_seconds: 300,
        tools: ['run_code', 'read_file', 'write_file', 'search_memory'],
        use_memory: false
      }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    if (!toolsRegistered) {
      registerBuiltinTools()
      toolsRegistered = true
    }

    const cfg = config as ReActAgentConfig
    const task = String(inputs.task || '')
    const contextStr = inputs.context ? String(inputs.context) : ''
    const maxIterations = cfg.max_iterations || 25
    const maxTimeMs = (cfg.max_time_seconds || 300) * 1000
    const model = cfg.model || 'gpt-4o'
    const provider = cfg.provider || 'openai'
    const permission = cfg.permissions || {}

    if (!task) {
      throw new NodeExecutionError(context.nodeId, this.type, 'Task is required')
    }

    const allowedToolNames = cfg.tools || ['run_code', 'read_file', 'write_file']
    const tools = allowedToolNames
      .map(name => getTool(name))
      .filter((t): t is AgentTool => t !== undefined)

    for (const tool of tools) {
      checkPermission(tool, permission)
    }

    const systemPrompt = cfg.system_prompt || buildAgentSystemPrompt(tools)

    const messages: Array<{ role: string; content: string }> = [
      { role: 'system', content: systemPrompt }
    ]

    if (contextStr) {
      messages.push({ role: 'system', content: `Context:\n${contextStr}` })
    }

    messages.push({ role: 'user', content: task })

    const thoughts: string[] = []
    const startTime = Date.now()
    let finalAnswer = ''

    const toolContext: ToolContext = {
      pool,
      nodeId: context.nodeId,
      signal: context.signal
    }

    for (let i = 0; i < maxIterations; i++) {
      if (context.signal?.aborted) {
        throw new AgentError('Agent aborted by user')
      }

      if (Date.now() - startTime > maxTimeMs) {
        throw new AgentError(`Agent timeout: exceeded ${maxTimeMs}ms`)
      }

      let llmOutput: string
      try {
        llmOutput = await window.api.ai.chat(messages, { model, provider })
      } catch (error) {
        const message = error instanceof Error ? error.message : 'LLM call failed'
        throw new AgentError(`Agent LLM error at iteration ${i}: ${message}`, { cause: error })
      }

      const parsed = parseAgentOutput(llmOutput)
      thoughts.push(parsed.thought)

      if (parsed.type === 'finish') {
        finalAnswer = parsed.finalAnswer || parsed.thought
        break
      }

      if (parsed.type === 'tool_call' && parsed.toolName) {
        messages.push({ role: 'assistant', content: llmOutput })

        const tool = getTool(parsed.toolName)
        if (!tool) {
          messages.push({ role: 'user', content: `Error: Tool '${parsed.toolName}' not found. Available tools: ${allowedToolNames.join(', ')}` })
          continue
        }

        if (!allowedToolNames.includes(tool.name)) {
          messages.push({ role: 'user', content: `Error: Tool '${tool.name}' is not enabled for this agent.` })
          continue
        }

        let toolResult: string
        try {
          if (tool.handlerFn) {
            toolResult = await tool.handlerFn(parsed.toolArgs || {}, toolContext)
          } else {
            toolResult = await this.executeHandler(tool, parsed.toolArgs || {}, toolContext)
          }
        } catch (error) {
          toolResult = `Error: ${error instanceof Error ? error.message : 'Tool execution failed'}`
        }

        messages.push({ role: 'user', content: buildToolResultPrompt(parsed.toolName, toolResult) })
        continue
      }

      messages.push({ role: 'assistant', content: llmOutput })
      messages.push({ role: 'user', content: 'Please use a tool or provide a FINISH response.' })
    }

    if (!finalAnswer && thoughts.length > 0) {
      finalAnswer = thoughts[thoughts.length - 1]
    }

    return {
      output: finalAnswer,
      iterations: thoughts.length,
      thoughts
    }
  }

  private async executeHandler(
    tool: AgentTool,
    args: Record<string, unknown>,
    context: ToolContext
  ): Promise<string> {
    switch (tool.handler) {
      case 'file_read': {
        const filePath = String(args.path || '')
        const fs = await import('fs/promises')
        return fs.readFile(filePath, 'utf-8')
      }
      case 'file_write': {
        const filePath = String(args.path || '')
        const content = String(args.content || '')
        const fs = await import('fs/promises')
        const { dirname } = await import('path')
        await fs.mkdir(dirname(filePath), { recursive: true })
        await fs.writeFile(filePath, content, 'utf-8')
        return `Written ${content.length} chars to ${filePath}`
      }
      case 'http': {
        const url = String(args.url || '')
        const method = String(args.method || 'GET')
        const response = await fetch(url, { method, headers: { 'Content-Type': 'application/json' } })
        return response.text()
      }
      default:
        return `Handler '${tool.handler}' not implemented yet.`
    }
  }
}
