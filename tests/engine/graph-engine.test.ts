import { describe, it, expect, beforeAll } from 'vitest'
import { Graph } from '../../src/engine/graph'
import { GraphEngine } from '../../src/engine/graph-engine'
import { NodeFactory, BaseNode, type NodeOutput, type NodeMetadata } from '../../src/engine/node-factory'
import { VariablePool } from '../../src/engine/variable-pool'

class MockStartNode extends BaseNode {
  type = 'mock-start'
  getMetadata(): NodeMetadata {
    return {
      type: 'mock-start', label: 'Start', icon: 'play', category: 'trigger', description: '',
      inputs: [],
      outputs: [{ name: 'output', label: 'Output', type: 'string', required: false }],
      defaultConfig: {}
    }
  }
  async run(): Promise<NodeOutput> { return { output: 'started' } }
}

class MockLLMNode extends BaseNode {
  type = 'mock-llm'
  getMetadata(): NodeMetadata {
    return {
      type: 'mock-llm', label: 'LLM', icon: 'robot', category: 'ai', description: '',
      inputs: [{ name: 'prompt', label: 'Prompt', type: 'string', required: true }],
      outputs: [{ name: 'output', label: 'Output', type: 'string', required: false }],
      defaultConfig: {}
    }
  }
  async run(inputs: Record<string, unknown>): Promise<NodeOutput> {
    return { output: `response: ${inputs.prompt}` }
  }
}

class MockEndNode extends BaseNode {
  type = 'mock-end'
  getMetadata(): NodeMetadata {
    return {
      type: 'mock-end', label: 'End', icon: 'stop', category: 'trigger', description: '',
      inputs: [{ name: 'input', label: 'Input', type: 'string', required: true }],
      outputs: [],
      defaultConfig: {}
    }
  }
  async run(inputs: Record<string, unknown>): Promise<NodeOutput> { return { final: inputs.input } }
}

class MockErrorNode extends BaseNode {
  type = 'mock-error'
  getMetadata(): NodeMetadata {
    return {
      type: 'mock-error', label: 'Error', icon: 'x', category: 'logic', description: '',
      inputs: [], outputs: [], defaultConfig: {}
    }
  }
  async run(): Promise<NodeOutput> { throw new Error('Intentional error') }
}

// Register mock nodes
const registry = new Map<string, new () => BaseNode>()
registry.set('mock-start', MockStartNode)
registry.set('mock-llm', MockLLMNode)
registry.set('mock-end', MockEndNode)
registry.set('mock-error', MockErrorNode)

// Patch NodeFactory for tests
const originalCreate = NodeFactory.create
;(NodeFactory as any).create = (type: string) => {
  const cls = registry.get(type)
  if (cls) return new cls()
  return originalCreate(type)
}

describe('GraphEngine', () => {
  it('should execute sequential workflow', async () => {
    const graph = new Graph()
    graph.addNode({ id: 'start', type: 'mock-start', data: {} })
    graph.addNode({ id: 'end', type: 'mock-end', data: {} })
    graph.addEdge({ id: 'e1', source: 'start', target: 'end' })

    const pool = new VariablePool()
    pool.set(['end', 'input'], 'test')

    const engine = new GraphEngine({ graph, variablePool: pool })
    const events: string[] = []

    for await (const event of engine.runSequential()) {
      events.push(event.type)
    }

    expect(events).toContain('graph:start')
    expect(events).toContain('node:complete')
    expect(events).toContain('graph:complete')
  })

  it('should execute parallel branches', async () => {
    const graph = new Graph()
    graph.addNode({ id: 'start', type: 'mock-start', data: {} })
    graph.addNode({ id: 'llm1', type: 'mock-llm', data: {} })
    graph.addNode({ id: 'llm2', type: 'mock-llm', data: {} })
    graph.addNode({ id: 'end', type: 'mock-end', data: {} })
    graph.addEdge({ id: 'e1', source: 'start', target: 'llm1' })
    graph.addEdge({ id: 'e2', source: 'start', target: 'llm2' })
    graph.addEdge({ id: 'e3', source: 'llm1', target: 'end' })
    graph.addEdge({ id: 'e4', source: 'llm2', target: 'end' })

    const pool = new VariablePool()
    pool.set(['llm1', 'prompt'], 'p1')
    pool.set(['llm2', 'prompt'], 'p2')
    pool.set(['end', 'input'], 'test')

    const engine = new GraphEngine({ graph, variablePool: pool })
    const completed: string[] = []

    for await (const event of engine.runParallel()) {
      if (event.type === 'node:complete' && event.nodeId) completed.push(event.nodeId)
    }

    expect(completed).toContain('start')
    expect(completed).toContain('llm1')
    expect(completed).toContain('llm2')
    expect(completed).toContain('end')
  })

  it('should emit error on node failure', async () => {
    const graph = new Graph()
    graph.addNode({ id: 'start', type: 'mock-start', data: {} })
    graph.addNode({ id: 'err', type: 'mock-error', data: {} })
    graph.addEdge({ id: 'e1', source: 'start', target: 'err' })

    const engine = new GraphEngine({ graph })
    const events: string[] = []

    try {
      for await (const event of engine.runSequential()) {
        events.push(event.type)
      }
    } catch { /* expected */ }

    expect(events).toContain('node:error')
  })

  it('should populate variable pool', async () => {
    const graph = new Graph()
    graph.addNode({ id: 'start', type: 'mock-start', data: {} })
    graph.addNode({ id: 'end', type: 'mock-end', data: {} })
    graph.addEdge({ id: 'e1', source: 'start', target: 'end' })

    const pool = new VariablePool()
    pool.set(['end', 'input'], 'test')
    const engine = new GraphEngine({ graph, variablePool: pool })

    for await (const _ of engine.runSequential()) { /* consume */ }

    expect(pool.get(['start', '__output__'])).toEqual({ output: 'started' })
  })
})
