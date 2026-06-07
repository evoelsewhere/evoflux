import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'

interface SubWorkflowConfig {
  workflow_id?: string
  inputs?: Record<string, string>
}

export class SubWorkflowNode extends BaseNode<SubWorkflowConfig> {
  readonly type = 'sub-workflow'

  getMetadata(): NodeMetadata {
    return {
      type: 'sub-workflow',
      label: 'Sub-Workflow',
      icon: 'apartment',
      category: 'agent',
      description: 'Embed another workflow as a node. Pass inputs, get outputs.',
      inputs: [
        { name: 'input', label: 'Input', type: 'string', required: false }
      ],
      outputs: [
        { name: 'output', label: 'Output', type: 'string', required: false }
      ],
      defaultConfig: { workflow_id: '', inputs: {} }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as SubWorkflowConfig
    const workflowId = cfg.workflow_id

    if (!workflowId) {
      throw new NodeExecutionError(context.nodeId, this.type, 'workflow_id is required')
    }

    // Load the sub-workflow DSL from storage
    try {
      const workflow = await window.api.workflow.load(workflowId)
      if (!workflow) {
        throw new NodeExecutionError(context.nodeId, this.type, `Workflow '${workflowId}' not found`)
      }

      // Execute the sub-workflow
      const result = await window.api.workflow.run(workflow, {
        inputs: { ...cfg.inputs, ...inputs }
      })

      if (result.success) {
        const lastResult = result.results?.[result.results.length - 1] as { output?: unknown } | undefined
        return { output: lastResult?.output ? String(lastResult.output) : '' }
      } else {
        throw new NodeExecutionError(context.nodeId, this.type, result.error || 'Sub-workflow failed')
      }
    } catch (error) {
      if (error instanceof NodeExecutionError) throw error
      const message = error instanceof Error ? error.message : 'Sub-workflow execution failed'
      throw new NodeExecutionError(context.nodeId, this.type, message, { cause: error })
    }
  }
}
