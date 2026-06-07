import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'
import { createSandbox } from '../sandbox/sandbox'

interface CodeConfig {
  language?: 'python' | 'javascript'
  code?: string
}

async function execCodeFallback(language: string, code: string): Promise<{ stdout: string; stderr: string }> {
  if (language === 'javascript') {
    try {
      const fn = new Function('input', code)
      const result = fn('')
      return { stdout: String(result ?? ''), stderr: '' }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error'
      return { stdout: '', stderr: message }
    }
  }
  return { stdout: '', stderr: `Sandbox not available for ${language}. Will be implemented in F8.` }
}

export class CodeNode extends BaseNode<CodeConfig> {
  readonly type = 'code'

  getMetadata(): NodeMetadata {
    return {
      type: 'code',
      label: 'Code',
      icon: 'code-sandbox',
      category: 'tools',
      description: 'Execute Python or JavaScript code in sandbox.',
      inputs: [
        { name: 'code', label: 'Code', type: 'string', required: true },
        { name: 'input', label: 'Input', type: 'string', required: false }
      ],
      outputs: [
        { name: 'output', label: 'Output', type: 'string', required: false },
        { name: 'error', label: 'Error', type: 'string', required: false }
      ],
      defaultConfig: { language: 'python', code: '' }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as CodeConfig
    const code = String(inputs.code || cfg.code || '')
    const language = cfg.language || 'python'
    const input = String(inputs.input || '')

    if (!code) {
      throw new NodeExecutionError(context.nodeId, this.type, 'Code is required')
    }

    try {
      const sandbox = await createSandbox({ workflowId: context.nodeId, runId: `code-${context.nodeId}` })
      const result = await sandbox.execCode(language, code, input || undefined)

      return {
        output: result.stdout,
        error: result.stderr || ''
      }
    } catch (error) {
      // Fallback to inline execution for JavaScript
      if (language === 'javascript') {
        const result = await execCodeFallback('javascript', code)
        return { output: result.stdout, error: result.stderr }
      }
      const message = error instanceof Error ? error.message : 'Code execution failed'
      throw new NodeExecutionError(context.nodeId, this.type, message, { cause: error })
    }
  }
}
