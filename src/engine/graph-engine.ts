import { Graph, type GraphNode } from './graph'
import { VariablePool } from './variable-pool'
import { NodeFactory, type NodeOutput } from './node-factory'
import { resolveValue } from './template-resolver'
import { LayerManager, type GraphEngineLayer, type EngineEvent } from './layers'
import { ExecutionLimitError, NodeExecutionError } from './errors'

export interface GraphEngineConfig {
  graph: Graph
  variablePool?: VariablePool
  layers?: GraphEngineLayer[]
  maxSteps?: number
  maxTimeMs?: number
  maxParallel?: number
}

export interface RunOptions {
  signal?: AbortSignal
  onEvent?: (event: EngineEvent) => void
}

export class GraphEngine {
  readonly graph: Graph
  readonly variablePool: VariablePool
  readonly layers: LayerManager

  private maxSteps: number
  private maxTimeMs: number
  private maxParallel: number

  constructor(config: GraphEngineConfig) {
    this.graph = config.graph
    this.variablePool = config.variablePool || new VariablePool()
    this.layers = new LayerManager()
    this.maxSteps = config.maxSteps ?? 1000
    this.maxTimeMs = config.maxTimeMs ?? 600000
    this.maxParallel = config.maxParallel ?? 5

    for (const layer of config.layers || []) {
      this.layers.add(layer)
    }
  }

  async *runSequential(options: RunOptions = {}): AsyncGenerator<EngineEvent> {
    const startTime = Date.now()
    let steps = 0
    let completed = 0
    let failed = 0

    const sorted = this.graph.topologicalSort()
    yield { type: 'graph:start', timestamp: Date.now() }
    await this.layers.emitGraphStart()

    try {
      for (const nodeId of sorted) {
        if (options.signal?.aborted) {
          yield { type: 'graph:aborted', timestamp: Date.now() }
          return
        }

        if (Date.now() - startTime > this.maxTimeMs) {
          throw new ExecutionLimitError(`Execution timeout: exceeded ${this.maxTimeMs}ms`)
        }

        if (++steps > this.maxSteps) {
          throw new ExecutionLimitError(`Execution limit: exceeded ${this.maxSteps} steps`)
        }

        const node = this.graph.getNode(nodeId)!
        const startEvent: EngineEvent = { type: 'node:start', nodeId, timestamp: Date.now() }
        yield startEvent
        await this.layers.emitNodeStart(node)

        try {
          const output = await this.executeNode(node, this.variablePool, options.signal)
          this.variablePool.set([nodeId, '__output__'], output)

          completed++
          const completeEvent: EngineEvent = { type: 'node:complete', nodeId, output, timestamp: Date.now() }
          yield completeEvent
          await this.layers.emitNodeEnd(node, output)
        } catch (error) {
          failed++
          const err = error instanceof Error ? error : new Error(String(error))
          const errorEvent: EngineEvent = { type: 'node:error', nodeId, error: err, timestamp: Date.now() }
          yield errorEvent
          await this.layers.emitNodeError(node, err)
          throw error
        }
      }

      const endEvent: EngineEvent = { type: 'graph:complete', timestamp: Date.now() }
      yield endEvent
    } finally {
      await this.layers.emitGraphEnd({ completed, failed })
    }
  }

  async *runParallel(options: RunOptions = {}): AsyncGenerator<EngineEvent> {
    const startTime = Date.now()
    let steps = 0
    let completed = 0
    let failed = 0

    const groups = this.graph.getParallelGroups()
    yield { type: 'graph:start', timestamp: Date.now() }
    await this.layers.emitGraphStart()

    try {
      for (const group of groups) {
        if (options.signal?.aborted) {
          yield { type: 'graph:aborted', timestamp: Date.now() }
          return
        }

        if (Date.now() - startTime > this.maxTimeMs) {
          throw new ExecutionLimitError(`Execution timeout: exceeded ${this.maxTimeMs}ms`)
        }

        if (group.length === 1) {
          steps++
          if (steps > this.maxSteps) {
            throw new ExecutionLimitError(`Execution limit: exceeded ${this.maxSteps} steps`)
          }

          const nodeId = group[0]
          const node = this.graph.getNode(nodeId)!
          yield { type: 'node:start', nodeId, timestamp: Date.now() }
          await this.layers.emitNodeStart(node)

          try {
            const output = await this.executeNode(node, this.variablePool, options.signal)
            this.variablePool.set([nodeId, '__output__'], output)
            completed++
            yield { type: 'node:complete', nodeId, output, timestamp: Date.now() }
            await this.layers.emitNodeEnd(node, output)
          } catch (error) {
            failed++
            const err = error instanceof Error ? error : new Error(String(error))
            yield { type: 'node:error', nodeId, error: err, timestamp: Date.now() }
            await this.layers.emitNodeError(node, err)
            throw error
          }
        } else {
          const batch = group.slice(0, this.maxParallel)
          if (batch.length < group.length) {
            console.warn(`[GraphEngine] Parallel group truncated from ${group.length} to ${batch.length} nodes (maxParallel=${this.maxParallel})`)
          }

          for (const nodeId of batch) {
            steps++
            if (steps > this.maxSteps) {
              throw new ExecutionLimitError(`Execution limit: exceeded ${this.maxSteps} steps`)
            }
            yield { type: 'node:start', nodeId, timestamp: Date.now() }
          }

          const results = await Promise.allSettled(
            batch.map(async (nodeId) => {
              const node = this.graph.getNode(nodeId)!
              await this.layers.emitNodeStart(node)
              const output = await this.executeNode(node, this.variablePool, options.signal)
              this.variablePool.set([nodeId, '__output__'], output)
              return { nodeId, output }
            })
          )

          for (const result of results) {
            if (result.status === 'fulfilled') {
              completed++
              const { nodeId, output } = result.value
              yield { type: 'node:complete', nodeId, output, timestamp: Date.now() }
              await this.layers.emitNodeEnd(this.graph.getNode(nodeId)!, output)
            } else {
              failed++
              const reason = result.reason instanceof Error ? result.reason : new Error(String(result.reason))
              yield { type: 'node:error', error: reason, timestamp: Date.now() }
              throw reason
            }
          }
        }
      }

      yield { type: 'graph:complete', timestamp: Date.now() }
    } finally {
      await this.layers.emitGraphEnd({ completed, failed })
    }
  }

  private async executeNode(
    node: GraphNode,
    pool: VariablePool,
    signal?: AbortSignal
  ): Promise<NodeOutput> {
    const nodeInstance = NodeFactory.create(node.type)
    const metadata = nodeInstance.getMetadata()

    const inputs: Record<string, unknown> = {}

    // Wire inputs from incoming edges — read source node's __output__ and map via sourceHandle
    for (const edge of this.graph.getEdges()) {
      if (edge.target === node.id) {
        const sourceOutput = pool.get([edge.source, '__output__'])
        if (sourceOutput !== undefined) {
          const targetPort = edge.targetHandle || metadata.inputs[0]?.name
          if (targetPort) {
            inputs[targetPort] = resolveValue(sourceOutput, pool)
          }
        }
      }
    }

    // Also read any values already in the pool for this node (e.g. from StartNode config)
    for (const port of metadata.inputs) {
      const value = pool.get([node.id, port.name])
      if (value !== undefined) {
        inputs[port.name] = resolveValue(value, pool)
      }
    }

    const config = resolveValue(node.data, pool)

    nodeInstance.validateInputs(inputs, metadata)

    try {
      return await nodeInstance.run(inputs, config, pool, {
        nodeId: node.id,
        signal
      })
    } catch (error) {
      if (error instanceof NodeExecutionError) throw error
      const message = error instanceof Error ? error.message : 'Unknown error'
      throw new NodeExecutionError(node.id, node.type, message, { cause: error })
    }
  }
}
