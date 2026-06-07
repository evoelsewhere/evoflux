import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'

interface LLMConfig {
  model?: string
  provider?: 'openai' | 'ollama'
  system_prompt?: string
  prompt?: string
  temperature?: number
  max_tokens?: number
  use_memory?: boolean
}

export class LLMNode extends BaseNode<LLMConfig> {
  readonly type = 'llm'

  getMetadata(): NodeMetadata {
    return {
      type: 'llm',
      label: 'LLM',
      icon: 'robot',
      category: 'ai',
      description: 'AI model invocation with prompt template.',
      inputs: [
        { name: 'prompt', label: 'Prompt', type: 'string', required: true },
        { name: 'system_prompt', label: 'System Prompt', type: 'string', required: false },
        { name: 'context', label: 'Context', type: 'string', required: false }
      ],
      outputs: [
        { name: 'output', label: 'Output', type: 'string', required: false },
        { name: 'usage', label: 'Token Usage', type: 'object', required: false }
      ],
      defaultConfig: {
        model: 'gpt-4o-mini',
        provider: 'openai',
        temperature: 0.7,
        max_tokens: 2048,
        system_prompt: '',
        use_memory: false
      }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    _context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as LLMConfig
    const prompt = String(inputs.prompt || cfg.prompt || '')
    const systemPrompt = String(inputs.system_prompt || cfg.system_prompt || '')
    const context = inputs.context ? String(inputs.context) : ''

    if (!prompt) {
      throw new NodeExecutionError(_context.nodeId, this.type, 'Prompt is required')
    }

    const messages: Array<{ role: string; content: string }> = []
    if (systemPrompt) {
      messages.push({ role: 'system', content: systemPrompt })
    }
    if (context) {
      messages.push({ role: 'system', content: `Context:\n${context}` })
    }
    messages.push({ role: 'user', content: prompt })

    try {
      const result = await window.api.ai.chat(messages, {
        model: cfg.model,
        provider: cfg.provider
      })
      return { output: result, usage: {} }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'LLM call failed'
      throw new NodeExecutionError(_context.nodeId, this.type, message, { cause: error })
    }
  }
}
