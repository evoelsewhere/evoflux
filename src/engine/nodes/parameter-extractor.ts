import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'

interface ParameterExtractorConfig {
  text?: string
  parameters?: Array<{ name: string; type: string; description?: string }>
  model?: string
}

export class ParameterExtractorNode extends BaseNode<ParameterExtractorConfig> {
  readonly type = 'parameter-extractor'

  getMetadata(): NodeMetadata {
    return {
      type: 'parameter-extractor',
      label: 'Parameter Extractor',
      icon: 'scan',
      category: 'ai',
      description: 'LLM-powered structured parameter extraction from text.',
      inputs: [
        { name: 'text', label: 'Text', type: 'string', required: true }
      ],
      outputs: [
        { name: 'parameters', label: 'Parameters', type: 'object', required: false },
        { name: 'raw', label: 'Raw Output', type: 'string', required: false }
      ],
      defaultConfig: { parameters: [], model: 'gpt-4o-mini' }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as ParameterExtractorConfig
    const text = String(inputs.text || cfg.text || '')
    const params = cfg.parameters || []

    if (!text) {
      throw new NodeExecutionError(context.nodeId, this.type, 'Text input is required')
    }

    const paramDescriptions = params.map(p =>
      `- ${p.name} (${p.type}): ${p.description || 'No description'}`
    ).join('\n')

    const prompt = `Extract the following parameters from the text below. Return as JSON object.\n\nParameters:\n${paramDescriptions}\n\nText:\n${text}\n\nReturn ONLY a valid JSON object.`

    try {
      const result = await window.api.ai.chat(
        [{ role: 'user', content: prompt }],
        { model: cfg.model || 'gpt-4o-mini' }
      )

      let extracted: Record<string, unknown> = {}
      try {
        const jsonMatch = result.match(/\{[\s\S]*\}/)
        if (jsonMatch) {
          extracted = JSON.parse(jsonMatch[0])
        }
      } catch {
        // Keep empty
      }

      return { parameters: extracted, raw: result }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Parameter extraction failed'
      throw new NodeExecutionError(context.nodeId, this.type, message, { cause: error })
    }
  }
}
