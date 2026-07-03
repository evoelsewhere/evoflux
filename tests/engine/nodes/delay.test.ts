import { describe, it, expect } from 'vitest'
import { NodeFactory } from '../../../src/engine/node-factory'
import { VariablePool } from '../../../src/engine/variable-pool'
import '../../../src/engine/nodes/index'

const pool = new VariablePool()
const ctx = { nodeId: 'delay-test', signal: undefined }

describe('DelayNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('delay')
    expect(meta.type).toBe('delay')
    expect(meta.category).toBe('logic')
    expect(meta.outputs.some(o => o.name === 'output')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'elapsed_ms')).toBe(true)
  })

  it('should delay for specified duration', async () => {
    const node = NodeFactory.create('delay')
    const start = Date.now()
    const output = await node.run({}, { duration_seconds: 0.1 }, pool, ctx)
    const elapsed = Date.now() - start
    expect(elapsed).toBeGreaterThanOrEqual(90)
    expect(output.elapsed_ms).toBeGreaterThanOrEqual(90)
  })

  it('should pass through input', async () => {
    const node = NodeFactory.create('delay')
    const output = await node.run({ input: 'hello' }, { duration_seconds: 0.05 }, pool, ctx)
    expect(output.output).toBe('hello')
  })

  it('should throw on negative duration', async () => {
    const node = NodeFactory.create('delay')
    await expect(node.run({}, { duration_seconds: -1 }, pool, ctx)).rejects.toThrow('non-negative')
  })

  it('should throw on excessive duration', async () => {
    const node = NodeFactory.create('delay')
    await expect(node.run({}, { duration_seconds: 400 }, pool, ctx)).rejects.toThrow('exceed 5 minutes')
  })
})
