import { describe, it, expect, beforeAll } from 'vitest'
import { NodeFactory } from '../../../src/engine/node-factory'
import { VariablePool } from '../../../src/engine/variable-pool'

// Import index which registers all nodes manually
import '../../../src/engine/nodes/index'

const pool = new VariablePool()
const ctx = { nodeId: 'test', signal: undefined }

describe('StartNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('start')
    expect(meta.type).toBe('start')
    expect(meta.category).toBe('trigger')
  })

  it('should run with variables', async () => {
    pool.set(['test', 'query'], 'hello')
    const node = NodeFactory.create('start')
    const output = await node.run({}, { variables: [{ name: 'query', type: 'string' }] }, pool, ctx)
    expect(output.query).toBe('hello')
  })
})

describe('EndNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('end')
    expect(meta.type).toBe('end')
  })

  it('should return final output', async () => {
    const node = NodeFactory.create('end')
    const output = await node.run({ output: 'result' }, {}, pool, ctx)
    expect(output.final_output).toBe('result')
  })
})

describe('ConditionNode', () => {
  it('should evaluate truthy expression', async () => {
    const node = NodeFactory.create('condition')
    const output = await node.run(
      { value: 'hello' },
      { expression: "value === 'hello'" },
      pool,
      ctx
    )
    expect(output.result).toBe(true)
    expect(output.true_branch).toBe('hello')
    expect(output.false_branch).toBe('')
  })

  it('should evaluate falsy expression', async () => {
    const node = NodeFactory.create('condition')
    const output = await node.run(
      { value: 'world' },
      { expression: "value === 'hello'" },
      pool,
      ctx
    )
    expect(output.result).toBe(false)
    expect(output.true_branch).toBe('')
    expect(output.false_branch).toBe('world')
  })

  it('should throw on invalid expression', async () => {
    const node = NodeFactory.create('condition')
    await expect(
      node.run({ value: 'test' }, { expression: 'invalid+++' }, pool, ctx)
    ).rejects.toThrow()
  })
})

describe('TemplateNode', () => {
  it('should resolve template', async () => {
    pool.set(['node1', 'name'], 'World')
    const node = NodeFactory.create('template')
    const output = await node.run(
      { template: 'Hello {{#node1.name#}}!' },
      {},
      pool,
      ctx
    )
    expect(output.output).toBe('Hello World!')
  })
})

describe('VariableAggregatorNode', () => {
  it('should concat values', async () => {
    const node = NodeFactory.create('variable-aggregator')
    const output = await node.run(
      { value_a: 'A', value_b: 'B' },
      { mode: 'concat' },
      pool,
      ctx
    )
    expect(output.output).toBe('A\nB')
  })

  it('should return first value', async () => {
    const node = NodeFactory.create('variable-aggregator')
    const output = await node.run(
      { value_a: 'A', value_b: 'B' },
      { mode: 'first' },
      pool,
      ctx
    )
    expect(output.output).toBe('A')
  })
})

describe('VariableAssignerNode', () => {
  it('should set variable in pool', async () => {
    const testPool = new VariablePool()
    const node = NodeFactory.create('variable-assigner')
    const output = await node.run(
      { value: 'assigned' },
      { variable_name: 'result' },
      testPool,
      ctx
    )
    expect(output.output).toBe('assigned')
    expect(testPool.get(['test', 'result'])).toBe('assigned')
  })
})

describe('IterationNode', () => {
  it('should parse JSON array input', async () => {
    const node = NodeFactory.create('iteration')
    const output = await node.run(
      { array: '[1, 2, 3]' },
      {},
      pool,
      ctx
    )
    expect(output.results).toEqual([1, 2, 3])
    expect(output.current_item).toBe('3')
    expect(output.index).toBe(2)
  })

  it('should handle array input directly', async () => {
    const node = NodeFactory.create('iteration')
    const output = await node.run(
      { array: ['a', 'b'] },
      {},
      pool,
      ctx
    )
    expect(output.results).toEqual(['a', 'b'])
  })
})

describe('NodeFactory', () => {
  it('should register all core nodes', () => {
    const types = NodeFactory.getRegisteredTypes()
    expect(types).toContain('start')
    expect(types).toContain('end')
    expect(types).toContain('llm')
    expect(types).toContain('code')
    expect(types).toContain('condition')
    expect(types).toContain('http-request')
    expect(types).toContain('template')
    expect(types).toContain('iteration')
    expect(types).toContain('loop')
    expect(types).toContain('variable-aggregator')
    expect(types).toContain('variable-assigner')
    expect(types).toContain('knowledge-retrieval')
    expect(types).toContain('parameter-extractor')
    expect(types).toContain('question-classifier')
  })

  it('should throw for unknown node type', () => {
    expect(() => NodeFactory.create('unknown')).toThrow()
  })
})
