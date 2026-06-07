import { describe, it, expect } from 'vitest'
import { MemoryGraph } from '../../../src/engine/memory/memory-graph'

describe('MemoryGraph', () => {
  it('should add and get semantic units', () => {
    const graph = new MemoryGraph()
    const id = graph.addSemantic({ type: 'fact', content: 'TypeScript is typed JS', metadata: {} })
    const unit = graph.getSemantic(id)
    expect(unit).toBeDefined()
    expect(unit!.content).toBe('TypeScript is typed JS')
    expect(unit!.type).toBe('fact')
    expect(unit!.accessCount).toBe(1)
  })

  it('should track access count', () => {
    const graph = new MemoryGraph()
    const id = graph.addSemantic({ type: 'fact', content: 'test', metadata: {} })
    graph.getSemantic(id)
    graph.getSemantic(id)
    expect(graph.getSemantic(id)!.accessCount).toBe(3)
  })

  it('should add and get episodes', () => {
    const graph = new MemoryGraph()
    const id = graph.addEpisode({
      runId: 'run-1',
      taskDescription: 'Build REST API',
      trajectory: [{ step: 1, nodeId: 'start', action: 'analyze', observation: 'ok', timestamp: Date.now() }],
      outcome: 'success',
      feedback: 'Good work'
    })
    const ep = graph.getEpisode(id)
    expect(ep).toBeDefined()
    expect(ep!.outcome).toBe('success')
  })

  it('should get successful episodes', () => {
    const graph = new MemoryGraph()
    graph.addEpisode({ runId: '1', taskDescription: 'task1', trajectory: [], outcome: 'success', feedback: '' })
    graph.addEpisode({ runId: '2', taskDescription: 'task2', trajectory: [], outcome: 'failure', feedback: '' })
    graph.addEpisode({ runId: '3', taskDescription: 'task3', trajectory: [], outcome: 'success', feedback: '' })
    expect(graph.getSuccessfulEpisodes()).toHaveLength(2)
  })

  it('should add and get procedures', () => {
    const graph = new MemoryGraph()
    const id = graph.addProcedure({
      name: 'Test Pattern',
      description: 'A testing pattern',
      pattern: 'Step 1 → Step 2',
      sourceEpisodes: [],
      usageCount: 0,
      successRate: 0.8,
      maturityScore: 0.5
    })
    const proc = graph.getProcedure(id)
    expect(proc).toBeDefined()
    expect(proc!.name).toBe('Test Pattern')
    expect(proc!.usageCount).toBe(1)
  })

  it('should add and query edges', () => {
    const graph = new MemoryGraph()
    const id1 = graph.addSemantic({ type: 'fact', content: 'A', metadata: {} })
    const id2 = graph.addSemantic({ type: 'fact', content: 'B', metadata: {} })
    const edgeId = graph.addEdge(id1, id2, 'ground', 0.9)

    const outgoing = graph.getEdgesFrom(id1)
    expect(outgoing).toHaveLength(1)
    expect(outgoing[0].targetId).toBe(id2)
    expect(outgoing[0].weight).toBe(0.9)

    const incoming = graph.getEdgesTo(id2)
    expect(incoming).toHaveLength(1)
    expect(incoming[0].sourceId).toBe(id1)
  })

  it('should remove semantic unit and its edges', () => {
    const graph = new MemoryGraph()
    const id1 = graph.addSemantic({ type: 'fact', content: 'A', metadata: {} })
    const id2 = graph.addSemantic({ type: 'fact', content: 'B', metadata: {} })
    graph.addEdge(id1, id2, 'ground')

    graph.removeSemantic(id1)
    expect(graph.getSemantic(id1)).toBeUndefined()
    expect(graph.getEdgesFrom(id1)).toHaveLength(0)
  })

  it('should return stats', () => {
    const graph = new MemoryGraph()
    graph.addSemantic({ type: 'fact', content: 'A', metadata: {} })
    graph.addSemantic({ type: 'document', content: 'B', metadata: {} })
    graph.addEpisode({ runId: '1', taskDescription: 'T', trajectory: [], outcome: 'success', feedback: '' })

    const stats = graph.getStats()
    expect(stats.semanticCount).toBe(2)
    expect(stats.episodicCount).toBe(1)
    expect(stats.proceduralCount).toBe(0)
  })

  it('should serialize to JSON', () => {
    const graph = new MemoryGraph()
    graph.addSemantic({ type: 'fact', content: 'test', metadata: { key: 'value' } })
    const json = graph.toJSON()
    expect(json.semantic).toHaveLength(1)
    expect(json.semantic[0].content).toBe('test')
    expect(json.semantic[0].embedding).toBeUndefined()
  })
})
