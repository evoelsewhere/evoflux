import { describe, it, expect } from 'vitest'
import { serializeGraph, deserializeGraph, validateDSL } from '../../src/engine/dsl'
import { Graph } from '../../src/engine/graph'

describe('DSL', () => {
  it('should serialize graph to DSL', () => {
    const graph = new Graph()
    graph.addNode({ id: 'a', type: 'start', data: { label: 'Start' } })
    graph.addNode({ id: 'b', type: 'end', data: { label: 'End' } })
    graph.addEdge({ id: 'e1', source: 'a', target: 'b' })

    const dsl = serializeGraph(graph, 'Test', 'A test workflow')
    expect(dsl.version).toBe('2.0')
    expect(dsl.name).toBe('Test')
    expect(dsl.graph.nodes).toHaveLength(2)
    expect(dsl.graph.edges).toHaveLength(1)
  })

  it('should deserialize DSL to graph', () => {
    const dsl = {
      version: '2.0' as const,
      name: 'Test',
      description: '',
      graph: {
        nodes: [
          { id: 'a', type: 'start', data: {} },
          { id: 'b', type: 'end', data: {} }
        ],
        edges: [
          { id: 'e1', source: 'a', target: 'b' }
        ]
      },
      config: {},
      metadata: { created_at: '', updated_at: '', tags: [] }
    }

    const graph = deserializeGraph(dsl)
    expect(graph.size).toBe(2)
    expect(graph.getEdges()).toHaveLength(1)
  })

  it('should roundtrip serialize/deserialize', () => {
    const graph = new Graph()
    graph.addNode({ id: 'a', type: 'start', data: { label: 'Start' } })
    graph.addNode({ id: 'b', type: 'llm', data: { model: 'gpt-4' } })
    graph.addNode({ id: 'c', type: 'end', data: { label: 'End' } })
    graph.addEdge({ id: 'e1', source: 'a', target: 'b' })
    graph.addEdge({ id: 'e2', source: 'b', target: 'c' })

    const dsl = serializeGraph(graph, 'Test', '')
    const graph2 = deserializeGraph(dsl)

    expect(graph2.size).toBe(graph.size)
    expect(graph2.getEdges()).toHaveLength(graph.getEdges().length)
    expect(graph2.topologicalSort()).toEqual(graph.topologicalSort())
  })

  it('should validate valid DSL', () => {
    const dsl = {
      version: '2.0',
      name: 'Test',
      description: '',
      graph: {
        nodes: [{ id: 'a', type: 'start', data: {} }],
        edges: []
      },
      config: {},
      metadata: { created_at: '', updated_at: '', tags: [] }
    }
    expect(validateDSL(dsl)).toBe(true)
  })

  it('should reject invalid DSL', () => {
    expect(validateDSL(null)).toBe(false)
    expect(validateDSL({})).toBe(false)
    expect(validateDSL({ version: '1.0' })).toBe(false)
    expect(validateDSL({ version: '2.0', name: 'Test' })).toBe(false)
  })
})
