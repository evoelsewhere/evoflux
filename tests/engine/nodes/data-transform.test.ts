import { describe, it, expect } from 'vitest'
import { NodeFactory } from '../../../src/engine/node-factory'
import { VariablePool } from '../../../src/engine/variable-pool'
import '../../../src/engine/nodes/index'

const pool = new VariablePool()
const ctx = { nodeId: 'data-transform-test', signal: undefined }

describe('DataTransformNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('data-transform')
    expect(meta.type).toBe('data-transform')
    expect(meta.category).toBe('logic')
    expect(meta.outputs.some(o => o.name === 'output')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'type')).toBe(true)
  })

  it('should extract by path', async () => {
    const node = NodeFactory.create('data-transform')
    const output = await node.run(
      { data: { users: [{ name: 'Alice' }, { name: 'Bob' }] } },
      { operations: [{ type: 'extract', path: 'users.0.name' }] },
      pool,
      ctx
    )
    expect(output.output).toBe('Alice')
  })

  it('should map array field', async () => {
    const node = NodeFactory.create('data-transform')
    const output = await node.run(
      { data: [{ name: 'Alice', age: 30 }, { name: 'Bob', age: 25 }] },
      { operations: [{ type: 'map', field: 'name' }] },
      pool,
      ctx
    )
    expect(output.output).toEqual(['Alice', 'Bob'])
  })

  it('should filter array', async () => {
    const node = NodeFactory.create('data-transform')
    const output = await node.run(
      { data: [{ name: 'Alice', role: 'admin' }, { name: 'Bob', role: 'user' }] },
      { operations: [{ type: 'filter', field: 'role', value: 'admin' }] },
      pool,
      ctx
    )
    expect((output.output as unknown[]).length).toBe(1)
    expect((output.output as Array<{ name: string }>)[0].name).toBe('Alice')
  })

  it('should merge objects', async () => {
    const node = NodeFactory.create('data-transform')
    const output = await node.run(
      { data: { a: 1, b: 2 } },
      { operations: [{ type: 'merge', source: { b: 3, c: 4 } }] },
      pool,
      ctx
    )
    expect(output.output).toEqual({ a: 1, b: 3, c: 4 })
  })

  it('should get keys', async () => {
    const node = NodeFactory.create('data-transform')
    const output = await node.run(
      { data: { name: 'Alice', age: 30 } },
      { operations: [{ type: 'keys' }] },
      pool,
      ctx
    )
    expect(output.output).toEqual(['name', 'age'])
  })

  it('should get length', async () => {
    const node = NodeFactory.create('data-transform')
    const output = await node.run(
      { data: [1, 2, 3, 4, 5] },
      { operations: [{ type: 'length' }] },
      pool,
      ctx
    )
    expect(output.output).toBe(5)
  })

  it('should flatten nested arrays', async () => {
    const node = NodeFactory.create('data-transform')
    const output = await node.run(
      { data: [[1, 2], [3, [4, 5]]] },
      { operations: [{ type: 'flatten' }] },
      pool,
      ctx
    )
    expect(output.output).toEqual([1, 2, 3, 4, 5])
  })

  it('should unique array', async () => {
    const node = NodeFactory.create('data-transform')
    const output = await node.run(
      { data: [1, 2, 2, 3, 3, 3] },
      { operations: [{ type: 'unique' }] },
      pool,
      ctx
    )
    expect(output.output).toEqual([1, 2, 3])
  })

  it('should sort array', async () => {
    const node = NodeFactory.create('data-transform')
    const output = await node.run(
      { data: [3, 1, 2] },
      { operations: [{ type: 'sort' }] },
      pool,
      ctx
    )
    expect(output.output).toEqual([1, 2, 3])
  })

  it('should stringify', async () => {
    const node = NodeFactory.create('data-transform')
    const output = await node.run(
      { data: { hello: 'world' } },
      { operations: [{ type: 'stringify' }] },
      pool,
      ctx
    )
    expect(typeof output.output).toBe('string')
    expect(output.output).toContain('hello')
  })

  it('should parse JSON string', async () => {
    const node = NodeFactory.create('data-transform')
    const output = await node.run(
      { data: '{"hello":"world"}' },
      { operations: [{ type: 'parse' }] },
      pool,
      ctx
    )
    expect(output.output).toEqual({ hello: 'world' })
  })

  it('should chain operations', async () => {
    const node = NodeFactory.create('data-transform')
    const output = await node.run(
      { data: { users: [{ name: 'Alice' }, { name: 'Bob' }, { name: 'Alice' }] } },
      { operations: [{ type: 'extract', path: 'users' }, { type: 'map', field: 'name' }, { type: 'unique' }] },
      pool,
      ctx
    )
    expect(output.output).toEqual(['Alice', 'Bob'])
  })

  it('should handle missing path gracefully', async () => {
    const node = NodeFactory.create('data-transform')
    const output = await node.run(
      { data: { name: 'Alice' } },
      { operations: [{ type: 'extract', path: 'nonexistent.path' }] },
      pool,
      ctx
    )
    expect(output.output).toBeUndefined()
  })
})
