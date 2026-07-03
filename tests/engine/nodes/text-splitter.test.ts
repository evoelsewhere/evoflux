import { describe, it, expect } from 'vitest'
import { NodeFactory } from '../../../src/engine/node-factory'
import { VariablePool } from '../../../src/engine/variable-pool'
import '../../../src/engine/nodes/index'

const pool = new VariablePool()
const ctx = { nodeId: 'text-split-test', signal: undefined }

describe('TextSplitterNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('text-splitter')
    expect(meta.type).toBe('text-splitter')
    expect(meta.category).toBe('tools')
    expect(meta.outputs.some(o => o.name === 'chunks')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'count')).toBe(true)
  })

  it('should split by character', async () => {
    const node = NodeFactory.create('text-splitter')
    const text = 'A'.repeat(2500)
    const output = await node.run(
      { text },
      { strategy: 'character', chunk_size: 1000, chunk_overlap: 100 },
      pool,
      ctx
    )
    expect(output.count).toBeGreaterThan(1)
    const chunks = output.chunks as string[]
    expect(chunks[0].length).toBeLessThanOrEqual(1000)
  })

  it('should split by sentence', async () => {
    const node = NodeFactory.create('text-splitter')
    const text = 'First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence.'
    const output = await node.run(
      { text },
      { strategy: 'sentence', chunk_size: 50, chunk_overlap: 10 },
      pool,
      ctx
    )
    expect(output.count).toBeGreaterThan(1)
  })

  it('should split by paragraph', async () => {
    const node = NodeFactory.create('text-splitter')
    const text = 'Paragraph one here.\n\nParagraph two here.\n\nParagraph three here.'
    const output = await node.run(
      { text },
      { strategy: 'paragraph', chunk_size: 100 },
      pool,
      ctx
    )
    expect(output.count).toBeGreaterThan(0)
  })

  it('should split recursively', async () => {
    const node = NodeFactory.create('text-splitter')
    const text = 'A'.repeat(3000)
    const output = await node.run(
      { text },
      { strategy: 'recursive', chunk_size: 1000, chunk_overlap: 200 },
      pool,
      ctx
    )
    expect(output.count).toBeGreaterThan(1)
    expect(output.first).toBeDefined()
  })

  it('should return single chunk for short text', async () => {
    const node = NodeFactory.create('text-splitter')
    const output = await node.run(
      { text: 'Short text' },
      { strategy: 'recursive', chunk_size: 1000 },
      pool,
      ctx
    )
    expect(output.count).toBe(1)
  })

  it('should throw on empty text', async () => {
    const node = NodeFactory.create('text-splitter')
    await expect(node.run({}, {}, pool, ctx)).rejects.toThrow('Text input is required')
  })
})
