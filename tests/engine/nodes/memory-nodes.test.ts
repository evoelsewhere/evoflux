import { describe, it, expect, beforeAll } from 'vitest'
import { openDatabase } from '../../../src/engine/db/database'
import { NodeFactory } from '../../../src/engine/node-factory'
import { VariablePool } from '../../../src/engine/variable-pool'
import '../../../src/engine/nodes/index'

const pool = new VariablePool()
const ctx = { nodeId: 'memory-test', signal: undefined }

beforeAll(() => {
  openDatabase(':memory:')
})

describe('KnowledgeRetrievalNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('knowledge-retrieval')
    expect(meta.type).toBe('knowledge-retrieval')
    expect(meta.category).toBe('ai')
    expect(meta.inputs.some(i => i.name === 'query')).toBe(true)
    expect(meta.inputs.some(i => i.name === 'content')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'results')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'formatted')).toBe(true)
  })

  it('should return empty results for empty query', async () => {
    const node = NodeFactory.create('knowledge-retrieval')
    const output = await node.run({}, { layer: 'all' }, pool, ctx)
    expect(output.results).toEqual([])
    expect(output.count).toBe(0)
  })

  it('should ingest knowledge then search it back', async () => {
    const node = NodeFactory.create('knowledge-retrieval')

    // Ingest
    const ingestOutput = await node.run(
      { content: 'TypeScript is a typed superset of JavaScript' },
      { mode: 'ingest', content_type: 'fact', workflow_id: 'test-wf' },
      pool,
      ctx
    )
    expect(ingestOutput.count).toBe(1)

    // Search
    const searchOutput = await node.run(
      { query: 'TypeScript' },
      { layer: 'semantic', top_k: 5, workflow_id: 'test-wf' },
      pool,
      ctx
    )
    expect(searchOutput.count).toBeGreaterThanOrEqual(1)
    expect(Array.isArray(searchOutput.results)).toBe(true)
    const results = searchOutput.results as Array<{ content: string }>
    expect(results[0].content).toContain('TypeScript')
  })

  it('should throw on ingest without content', async () => {
    const node = NodeFactory.create('knowledge-retrieval')
    await expect(
      node.run({}, { mode: 'ingest' }, pool, ctx)
    ).rejects.toThrow('Content is required')
  })
})
