import { describe, it, expect } from 'vitest'
import { NodeFactory } from '../../../src/engine/node-factory'
import { VariablePool } from '../../../src/engine/variable-pool'
import '../../../src/engine/nodes/index'

const pool = new VariablePool()
const ctx = { nodeId: 'trigger-test', signal: undefined }

describe('ManualTriggerNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('manual-trigger')
    expect(meta.type).toBe('manual-trigger')
    expect(meta.category).toBe('trigger')
  })

  it('should return variables from pool', async () => {
    const p = new VariablePool()
    p.set(['trigger-test', 'query'], 'hello')
    p.set(['trigger-test', 'count'], 42)
    const node = NodeFactory.create('manual-trigger')
    const output = await node.run({}, { variables: [{ name: 'query', type: 'string' }, { name: 'count', type: 'number' }] }, p, ctx)
    expect(output.query).toBe('hello')
    expect(output.count).toBe(42)
  })

  it('should use default values when pool is empty', async () => {
    const p = new VariablePool()
    const node = NodeFactory.create('manual-trigger')
    const output = await node.run({}, { variables: [{ name: 'city', type: 'string', default: 'Hanoi' }] }, p, ctx)
    expect(output.city).toBe('Hanoi')
  })

  it('should handle empty variables', async () => {
    const node = NodeFactory.create('manual-trigger')
    const output = await node.run({}, { variables: [] }, pool, ctx)
    expect(output).toEqual({})
  })
})

describe('WebhookTriggerNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('webhook-trigger')
    expect(meta.type).toBe('webhook-trigger')
    expect(meta.category).toBe('trigger')
    expect(meta.outputs.length).toBeGreaterThan(0)
  })

  it('should return stub output', async () => {
    const node = NodeFactory.create('webhook-trigger')
    const output = await node.run({}, {}, pool, ctx)
    expect(output.method).toBe('POST')
    expect(output.body).toBe('')
  })
})

describe('ScheduleTriggerNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('schedule-trigger')
    expect(meta.type).toBe('schedule-trigger')
    expect(meta.category).toBe('trigger')
  })

  it('should return timestamp', async () => {
    const node = NodeFactory.create('schedule-trigger')
    const output = await node.run({}, {}, pool, ctx)
    expect(output.timestamp).toBeDefined()
    expect(new Date(output.timestamp as string).getTime()).not.toBeNaN()
  })
})
