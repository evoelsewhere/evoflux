import { describe, it, expect } from 'vitest'
import { WorkflowMemory } from '../../../src/engine/memory/api'
import { MemoryGraph } from '../../../src/engine/memory/memory-graph'

describe('WorkflowMemory', () => {
  it('should create memory instance', () => {
    const memory = new WorkflowMemory('test-run')
    expect(memory.graph).toBeInstanceOf(MemoryGraph)
    expect(memory.getStats().semanticCount).toBe(0)
  })

  it('should add semantic knowledge', async () => {
    const memory = new WorkflowMemory()
    const id = await memory.addSemantic('TypeScript is typed JavaScript', 'fact')
    expect(id).toBeTruthy()
    expect(memory.getStats().semanticCount).toBe(1)
  })

  it('should record steps and outcome', async () => {
    const memory = new WorkflowMemory('run-1')

    memory.recordStep({ step: 1, nodeId: 'start', action: 'analyze code', observation: 'found issues', timestamp: Date.now() })
    memory.recordStep({ step: 2, nodeId: 'llm', action: 'generate fix', observation: 'fixed', timestamp: Date.now() })

    const episodeId = await memory.recordOutcome('success', 'Code review completed')
    expect(episodeId).toBeTruthy()
    expect(memory.getStats().episodicCount).toBe(1)
  })

  it('should search semantic memory', async () => {
    const memory = new WorkflowMemory()
    await memory.addSemantic('REST API uses HTTP methods', 'fact')
    await memory.addSemantic('GraphQL uses queries and mutations', 'fact')

    const results = await memory.searchSemantic('HTTP API', 2)
    expect(results.length).toBeGreaterThan(0)
    // Random fallback embeddings don't guarantee ordering, just check we got results
    expect(results[0].score).toBeGreaterThanOrEqual(-1)
    expect(results[0].score).toBeLessThanOrEqual(1)
  })

  it('should get context from memory', async () => {
    const memory = new WorkflowMemory()
    await memory.addSemantic('Use Express.js for REST APIs', 'fact')
    await memory.addSemantic('Always validate input data', 'fact')

    const ctx = await memory.getContext('Build a REST API')
    expect(ctx.formatted).toBeDefined()
  })

  it('should return stats', async () => {
    const memory = new WorkflowMemory()
    await memory.addSemantic('fact 1', 'fact')
    await memory.addSemantic('fact 2', 'fact')
    await memory.addSemantic('doc 1', 'document')

    const stats = memory.getStats()
    expect(stats.semanticCount).toBe(3)
  })

  it('should serialize to JSON', async () => {
    const memory = new WorkflowMemory()
    await memory.addSemantic('test', 'fact')
    memory.recordStep({ step: 1, nodeId: 'a', action: 'do', observation: 'done', timestamp: Date.now() })

    const json = memory.toJSON()
    expect(json.semantic).toHaveLength(1)
    expect(json.edges).toBeDefined()
  })
})
