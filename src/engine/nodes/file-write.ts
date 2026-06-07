import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'
import { createSandbox } from '../sandbox/sandbox'

interface FileWriteConfig {
  path?: string
  content?: string
  create_dirs?: boolean
}

export class FileWriteNode extends BaseNode<FileWriteConfig> {
  readonly type = 'file-write'

  getMetadata(): NodeMetadata {
    return {
      type: 'file-write',
      label: 'File Write',
      icon: 'file-text',
      category: 'tools',
      description: 'Write content to a file in the sandbox.',
      inputs: [
        { name: 'path', label: 'File Path', type: 'string', required: true },
        { name: 'content', label: 'Content', type: 'string', required: true }
      ],
      outputs: [
        { name: 'path', label: 'Written Path', type: 'string', required: false },
        { name: 'bytes', label: 'Bytes Written', type: 'number', required: false }
      ],
      defaultConfig: { create_dirs: true }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as FileWriteConfig
    const filePath = String(inputs.path || cfg.path || '')
    const content = String(inputs.content || cfg.content || '')

    if (!filePath) throw new NodeExecutionError(context.nodeId, this.type, 'File path is required')

    try {
      const sandbox = await createSandbox({ workflowId: context.nodeId, runId: `fw-${context.nodeId}` })
      await sandbox.writeFile(filePath, content)
      return { path: filePath, bytes: content.length }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'File write failed'
      throw new NodeExecutionError(context.nodeId, this.type, message, { cause: error })
    }
  }
}
