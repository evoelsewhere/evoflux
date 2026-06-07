import type { GraphEngineLayer } from '../layers'
import type { GraphNode } from '../graph'
import type { NodeOutput } from '../node-factory'
import { ExecutionLimitError } from '../errors'
import { createRun, updateRunStatus, createNodeRun, updateNodeRunStatus } from '../db/run-repo'

export class PersistenceLayer implements GraphEngineLayer {
  name = 'persistence'
  private runId: string | null = null
  private nodeRunIds = new Map<string, string>()
  private workflowId: string

  constructor(workflowId: string) {
    this.workflowId = workflowId
  }

  onGraphStart(): void {
    this.nodeRunIds.clear()
    try {
      const run = createRun(this.workflowId)
      this.runId = run.id
    } catch {
      // DB not available, skip persistence
    }
  }

  onGraphEnd(result: { completed: number; failed: number }): void {
    if (!this.runId) return
    try {
      const status = result.failed > 0 ? 'failed' : 'completed'
      updateRunStatus(this.runId, status, { completed: result.completed, failed: result.failed })
    } catch {
      // Best effort
    }
  }

  onNodeStart(node: GraphNode): void {
    if (!this.runId) return
    try {
      const nodeRun = createNodeRun(this.runId, node.id, node.type)
      this.nodeRunIds.set(node.id, nodeRun.id)
    } catch {
      // Best effort
    }
  }

  onNodeEnd(node: GraphNode, output: NodeOutput): void {
    const nodeRunId = this.nodeRunIds.get(node.id)
    if (!nodeRunId) return
    try {
      updateNodeRunStatus(nodeRunId, 'completed', output)
    } catch {
      // Best effort
    }
  }

  onNodeError(node: GraphNode, error: Error): void {
    const nodeRunId = this.nodeRunIds.get(node.id)
    if (!nodeRunId) return
    try {
      updateNodeRunStatus(nodeRunId, 'error', undefined, error.message)
    } catch {
      // Best effort
    }
  }

  getRunId(): string | null {
    return this.runId
  }
}

export class ExecutionLimitsLayer implements GraphEngineLayer {
  name = 'limits'
  private stepCount = 0
  private startTime = 0

  constructor(
    private maxSteps: number = 1000,
    private maxTimeMs: number = 600000
  ) {}

  onGraphStart(): void {
    this.stepCount = 0
    this.startTime = Date.now()
  }

  onNodeStart(_node: GraphNode): void {
    this.stepCount++

    if (this.stepCount > this.maxSteps) {
      throw new ExecutionLimitError(`Execution limit exceeded: ${this.maxSteps} steps`)
    }

    if (Date.now() - this.startTime > this.maxTimeMs) {
      throw new ExecutionLimitError(`Execution timeout: exceeded ${this.maxTimeMs}ms`)
    }
  }
}

export class TokenTrackingLayer implements GraphEngineLayer {
  name = 'token-tracking'
  private totalTokens = 0
  private nodeTokens = new Map<string, number>()

  onNodeEnd(node: GraphNode, output: NodeOutput): void {
    const usage = output?.usage as { total_tokens?: number } | undefined
    if (usage?.total_tokens) {
      this.totalTokens += usage.total_tokens
      this.nodeTokens.set(node.id, usage.total_tokens)
    }
  }

  getTotalTokens(): number {
    return this.totalTokens
  }

  getNodeTokens(nodeId: string): number {
    return this.nodeTokens.get(nodeId) || 0
  }
}
