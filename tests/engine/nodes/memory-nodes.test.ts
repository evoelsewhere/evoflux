import { describe, it, expect } from 'vitest'
import { NodeFactory } from '../../../src/engine/node-factory'
import { VariablePool } from '../../../src/engine/variable-pool'
import '../../../src/engine/nodes/index'

const pool = new VariablePool()
const ctx = { nodeId: 'memory-test', signal: undefined }

describe('KnowledgeRetrievalNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('knowledge-retrieval')
    expect(meta.type).toBe('knowledge-retrieval')
    expect(meta.category).toBe('ai')
    expect(meta.inputs.some(i => i.name === 'query')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'results')).toBe(true)
  })

  it('should search and return formatted results', async () => {
    const node = NodeFactory.create('knowledge-retrieval')
    const output = await node.run(
      { query: 'test query' },
      { layer: 'all', top_k: 5 },
      pool,
      ctx
    )
    expect(typeof output.results).toBe('string')
    expect(typeof output.count).toBe('number')
  })

  it('should return empty for empty query', async () => {
    const node = NodeFactory.create('knowledge-retrieval')
    const output = await node.run(
      { query: '' },
      { layer: 'all' },
      pool,
      ctx
    )
    expect(output.results).toBe('')
    expect(output.count).toBe(0)
  })
})
