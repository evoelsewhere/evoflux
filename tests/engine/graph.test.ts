import { describe, it, expect } from 'vitest'
import { Graph } from '../../src/engine/graph'
import { CycleDetectedError } from '../../src/engine/errors'

describe('Graph', () => {
  it('should add and get nodes', () => {
    const graph = new Graph()
    graph.addNode({ id: 'a', type: 'start', data: {} })
    expect(graph.getNode('a')).toEqual({ id: 'a', type: 'start', data: {} })
    expect(graph.size).toBe(1)
  })

  it('should throw on duplicate node', () => {
    const graph = new Graph()
    graph.addNode({ id: 'a', type: 'start', data: {} })
    expect(() => graph.addNode({ id: 'a', type: 'start', data: {} })).toThrow()
  })

  it('should remove node and edges', () => {
    const graph = new Graph()
    graph.addNode({ id: 'a', type: 'start', data: {} })
    graph.addNode({ id: 'b', type: 'end', data: {} })
    graph.addEdge({ id: 'e1', source: 'a', target: 'b' })
    graph.removeNode('a')
    expect(graph.size).toBe(1)
    expect(graph.getEdges()).toHaveLength(0)
  })

  it('should add edges', () => {
    const graph = new Graph()
    graph.addNode({ id: 'a', type: 'start', data: {} })
    graph.addNode({ id: 'b', type: 'end', data: {} })
    graph.addEdge({ id: 'e1', source: 'a', target: 'b' })
    expect(graph.getEdges()).toHaveLength(1)
    expect(graph.getOutgoing('a')).toEqual(['b'])
    expect(graph.getIncoming('b')).toEqual(['a'])
  })

  it('should throw on edge with missing nodes', () => {
    const graph = new Graph()
    expect(() => graph.addEdge({ id: 'e1', source: 'a', target: 'b' })).toThrow()
  })

  it('should get root nodes', () => {
    const graph = new Graph()
    graph.addNode({ id: 'a', type: 'start', data: {} })
    graph.addNode({ id: 'b', type: 'llm', data: {} })
    graph.addEdge({ id: 'e1', source: 'a', target: 'b' })
    expect(graph.getRoots()).toEqual(['a'])
  })

  it('should get leaf nodes', () => {
    const graph = new Graph()
    graph.addNode({ id: 'a', type: 'start', data: {} })
    graph.addNode({ id: 'b', type: 'end', data: {} })
    graph.addEdge({ id: 'e1', source: 'a', target: 'b' })
    expect(graph.getLeaves()).toEqual(['b'])
  })

  it('should topological sort linear graph', () => {
    const graph = new Graph()
    graph.addNode({ id: 'a', type: 'start', data: {} })
    graph.addNode({ id: 'b', type: 'llm', data: {} })
    graph.addNode({ id: 'c', type: 'end', data: {} })
    graph.addEdge({ id: 'e1', source: 'a', target: 'b' })
    graph.addEdge({ id: 'e2', source: 'b', target: 'c' })
    const sorted = graph.topologicalSort()
    expect(sorted).toEqual(['a', 'b', 'c'])
  })

  it('should topological sort diamond graph', () => {
    const graph = new Graph()
    graph.addNode({ id: 'a', type: 'start', data: {} })
    graph.addNode({ id: 'b', type: 'llm', data: {} })
    graph.addNode({ id: 'c', type: 'llm', data: {} })
    graph.addNode({ id: 'd', type: 'end', data: {} })
    graph.addEdge({ id: 'e1', source: 'a', target: 'b' })
    graph.addEdge({ id: 'e2', source: 'a', target: 'c' })
    graph.addEdge({ id: 'e3', source: 'b', target: 'd' })
    graph.addEdge({ id: 'e4', source: 'c', target: 'd' })
    const sorted = graph.topologicalSort()
    expect(sorted).toHaveLength(4)
    expect(sorted.indexOf('a')).toBeLessThan(sorted.indexOf('b'))
    expect(sorted.indexOf('a')).toBeLessThan(sorted.indexOf('c'))
    expect(sorted.indexOf('b')).toBeLessThan(sorted.indexOf('d'))
    expect(sorted.indexOf('c')).toBeLessThan(sorted.indexOf('d'))
  })

  it('should detect cycle', () => {
    const graph = new Graph()
    graph.addNode({ id: 'a', type: 'start', data: {} })
    graph.addNode({ id: 'b', type: 'llm', data: {} })
    graph.addEdge({ id: 'e1', source: 'a', target: 'b' })
    graph.addEdge({ id: 'e2', source: 'b', target: 'a' })
    expect(() => graph.topologicalSort()).toThrow(CycleDetectedError)
  })

  it('should get parallel groups', () => {
    const graph = new Graph()
    graph.addNode({ id: 'a', type: 'start', data: {} })
    graph.addNode({ id: 'b', type: 'llm', data: {} })
    graph.addNode({ id: 'c', type: 'llm', data: {} })
    graph.addNode({ id: 'd', type: 'end', data: {} })
    graph.addEdge({ id: 'e1', source: 'a', target: 'b' })
    graph.addEdge({ id: 'e2', source: 'a', target: 'c' })
    graph.addEdge({ id: 'e3', source: 'b', target: 'd' })
    graph.addEdge({ id: 'e4', source: 'c', target: 'd' })
    const groups = graph.getParallelGroups()
    expect(groups).toEqual([['a'], ['b', 'c'], ['d']])
  })

  it('should serialize to JSON', () => {
    const graph = new Graph()
    graph.addNode({ id: 'a', type: 'start', data: { label: 'Start' } })
    graph.addNode({ id: 'b', type: 'end', data: { label: 'End' } })
    graph.addEdge({ id: 'e1', source: 'a', target: 'b' })
    const json = graph.toJSON()
    expect(json.nodes).toHaveLength(2)
    expect(json.edges).toHaveLength(1)
  })
})
