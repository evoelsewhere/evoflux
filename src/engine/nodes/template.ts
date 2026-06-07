import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { resolveTemplate } from '../template-resolver'

interface TemplateConfig {
  template?: string
}

export class TemplateNode extends BaseNode<TemplateConfig> {
  readonly type = 'template'

  getMetadata(): NodeMetadata {
    return {
      type: 'template',
      label: 'Template',
      icon: 'file-text',
      category: 'logic',
      description: 'Render a template string with variable substitution.',
      inputs: [
        { name: 'template', label: 'Template', type: 'string', required: true }
      ],
      outputs: [
        { name: 'output', label: 'Output', type: 'string', required: false }
      ],
      defaultConfig: { template: '' }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    pool: VariablePool,
    _context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as TemplateConfig
    const template = String(inputs.template || cfg.template || '')
    const output = resolveTemplate(template, pool)
    return { output }
  }
}
