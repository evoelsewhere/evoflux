import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'
import { createSandbox } from '../sandbox/sandbox'
import { nanoid } from 'nanoid'

interface ShellConfig {
  command?: string
  timeout_ms?: number
  cwd?: string
}

export class ShellNode extends BaseNode<ShellConfig> {
  readonly type = 'shell'

  getMetadata(): NodeMetadata {
    return {
      type: 'shell',
      label: 'Shell',
      icon: 'code',
      category: 'tools',
      description: 'Execute a shell command in sandbox.',
      inputs: [
        { name: 'command', label: 'Command', type: 'string', required: true }
      ],
      outputs: [
        { name: 'stdout', label: 'Stdout', type: 'string', required: false },
        { name: 'stderr', label: 'Stderr', type: 'string', required: false },
        { name: 'exit_code', label: 'Exit Code', type: 'number', required: false }
      ],
      defaultConfig: { timeout_ms: 30000 }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as ShellConfig
    const inputCmd = typeof inputs.command === 'string' ? inputs.command : ''
    const command = inputCmd || String(cfg.command || '')
    if (!command) throw new NodeExecutionError(context.nodeId, this.type, 'Command is required')

    try {
      const sandbox = await createSandbox({ workflowId: `wf-${context.nodeId}`, runId: `run-${nanoid(8)}` })
      try {
        const result = await sandbox.exec(command, {
          timeoutMs: cfg.timeout_ms || 30000,
          cwd: cfg.cwd
        })
        return { stdout: result.stdout, stderr: result.stderr, exit_code: result.exitCode }
      } finally {
        await sandbox.destroy().catch(() => {})
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Shell execution failed'
      throw new NodeExecutionError(context.nodeId, this.type, message, { cause: error })
    }
  }
}
