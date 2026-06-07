import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'

interface QuestionClassifierConfig {
  question?: string
  categories?: string[]
  model?: string
}

export class QuestionClassifierNode extends BaseNode<QuestionClassifierConfig> {
  readonly type = 'question-classifier'

  getMetadata(): NodeMetadata {
    return {
      type: 'question-classifier',
      label: 'Question Classifier',
      icon: 'tags',
      category: 'ai',
      description: 'LLM-powered N-way classification of input text.',
      inputs: [
        { name: 'text', label: 'Text', type: 'string', required: true }
      ],
      outputs: [
        { name: 'category', label: 'Category', type: 'string', required: false },
        { name: 'confidence', label: 'Confidence', type: 'number', required: false },
        { name: 'raw', label: 'Raw Output', type: 'string', required: false }
      ],
      defaultConfig: { categories: [], model: 'gpt-4o-mini' }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as QuestionClassifierConfig
    const text = String(inputs.text || '')
    const categories = cfg.categories || []

    if (!text) {
      throw new NodeExecutionError(context.nodeId, this.type, 'Text input is required')
    }

    if (categories.length === 0) {
      throw new NodeExecutionError(context.nodeId, this.type, 'At least one category is required')
    }

    const prompt = `Classify the following text into one of these categories: ${categories.join(', ')}\n\nText: ${text}\n\nReturn ONLY the category name.`

    try {
      const result = await window.api.ai.chat(
        [{ role: 'user', content: prompt }],
        { model: cfg.model || 'gpt-4o-mini' }
      )

      const category = result.trim()
      const matched = categories.find(c => category.toLowerCase().includes(c.toLowerCase()))

      return {
        category: matched || category,
        confidence: matched ? 1.0 : 0.5,
        raw: result
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Classification failed'
      throw new NodeExecutionError(context.nodeId, this.type, message, { cause: error })
    }
  }
}
