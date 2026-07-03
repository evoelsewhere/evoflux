import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'

interface TextTransformConfig {
  text?: string
  operations?: Array<{ type: string; value?: string; replacement?: string; flags?: string }>
}

type OperationType =
  | 'uppercase' | 'lowercase' | 'trim' | 'truncate'
  | 'replace' | 'regex_replace' | 'prefix' | 'suffix'
  | 'strip_tags' | 'decode_entities' | 'extract_urls' | 'extract_emails'

export class TextTransformNode extends BaseNode<TextTransformConfig> {
  readonly type = 'text-transform'

  getMetadata(): NodeMetadata {
    return {
      type: 'text-transform',
      label: 'Text Transform',
      icon: 'edit',
      category: 'logic',
      description: 'Apply string operations: uppercase, lowercase, trim, replace, regex, truncate, extract URLs/emails.',
      inputs: [
        { name: 'text', label: 'Text', type: 'string', required: true }
      ],
      outputs: [
        { name: 'output', label: 'Transformed Text', type: 'string', required: false },
        { name: 'length', label: 'Length', type: 'number', required: false }
      ],
      defaultConfig: { operations: [{ type: 'trim' }] }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as TextTransformConfig
    let text = String(inputs.text || cfg.text || '')

    if (!text && text !== '') {
      throw new NodeExecutionError(context.nodeId, this.type, 'Text input is required')
    }

    const operations = cfg.operations || [{ type: 'trim' }]

    for (const op of operations) {
      text = applyOperation(text, op.type as OperationType, op)
    }

    return {
      output: text,
      length: text.length
    }
  }
}

function applyOperation(
  text: string,
  type: OperationType,
  op: { value?: string; replacement?: string; flags?: string }
): string {
  switch (type) {
    case 'uppercase':
      return text.toUpperCase()
    case 'lowercase':
      return text.toLowerCase()
    case 'trim':
      return text.trim()
    case 'truncate': {
      const maxLen = parseInt(op.value || '500', 10)
      if (text.length <= maxLen) return text
      return text.substring(0, maxLen) + '...'
    }
    case 'replace': {
      const search = op.value || ''
      const repl = op.replacement || ''
      return text.replaceAll(search, repl)
    }
    case 'regex_replace': {
      try {
        const flags = op.flags || 'g'
        const regex = new RegExp(op.value || '', flags)
        return text.replace(regex, op.replacement || '')
      } catch {
        return text
      }
    }
    case 'prefix':
      return (op.value || '') + text
    case 'suffix':
      return text + (op.value || '')
    case 'strip_tags':
      return text.replace(/<[^>]+>/g, '')
    case 'decode_entities':
      return text
        .replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/&nbsp;/g, ' ')
    case 'extract_urls': {
      const urls = text.match(/https?:\/\/[^\s<>"{}|\\^`[\]]+/g) || []
      return urls.join('\n')
    }
    case 'extract_emails': {
      const emails = text.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g) || []
      return emails.join('\n')
    }
    default:
      return text
  }
}
