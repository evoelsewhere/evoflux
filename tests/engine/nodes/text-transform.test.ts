import { describe, it, expect } from 'vitest'
import { NodeFactory } from '../../../src/engine/node-factory'
import { VariablePool } from '../../../src/engine/variable-pool'
import '../../../src/engine/nodes/index'

const pool = new VariablePool()
const ctx = { nodeId: 'text-transform-test', signal: undefined }

describe('TextTransformNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('text-transform')
    expect(meta.type).toBe('text-transform')
    expect(meta.category).toBe('logic')
    expect(meta.outputs.some(o => o.name === 'output')).toBe(true)
  })

  it('should uppercase', async () => {
    const node = NodeFactory.create('text-transform')
    const output = await node.run({ text: 'hello world' }, { operations: [{ type: 'uppercase' }] }, pool, ctx)
    expect(output.output).toBe('HELLO WORLD')
  })

  it('should lowercase', async () => {
    const node = NodeFactory.create('text-transform')
    const output = await node.run({ text: 'HELLO WORLD' }, { operations: [{ type: 'lowercase' }] }, pool, ctx)
    expect(output.output).toBe('hello world')
  })

  it('should trim', async () => {
    const node = NodeFactory.create('text-transform')
    const output = await node.run({ text: '  hello  ' }, { operations: [{ type: 'trim' }] }, pool, ctx)
    expect(output.output).toBe('hello')
  })

  it('should truncate', async () => {
    const node = NodeFactory.create('text-transform')
    const output = await node.run({ text: 'Hello World' }, { operations: [{ type: 'truncate', value: '5' }] }, pool, ctx)
    expect(output.output).toBe('Hello...')
  })

  it('should replace', async () => {
    const node = NodeFactory.create('text-transform')
    const output = await node.run({ text: 'hello world' }, { operations: [{ type: 'replace', value: 'world', replacement: 'TypeScript' }] }, pool, ctx)
    expect(output.output).toBe('hello TypeScript')
  })

  it('should regex replace', async () => {
    const node = NodeFactory.create('text-transform')
    const output = await node.run({ text: 'abc 123 def 456' }, { operations: [{ type: 'regex_replace', value: '\\d+', replacement: 'NUM' }] }, pool, ctx)
    expect(output.output).toBe('abc NUM def NUM')
  })

  it('should extract URLs', async () => {
    const node = NodeFactory.create('text-transform')
    const output = await node.run({ text: 'Visit https://example.com and http://test.org for more.' }, { operations: [{ type: 'extract_urls' }] }, pool, ctx)
    expect(output.output).toContain('https://example.com')
    expect(output.output).toContain('http://test.org')
  })

  it('should strip HTML tags', async () => {
    const node = NodeFactory.create('text-transform')
    const output = await node.run({ text: '<p>Hello <b>world</b></p>' }, { operations: [{ type: 'strip_tags' }] }, pool, ctx)
    expect(output.output).toBe('Hello world')
  })

  it('should chain operations', async () => {
    const node = NodeFactory.create('text-transform')
    const output = await node.run(
      { text: '  Hello World  ' },
      { operations: [{ type: 'trim' }, { type: 'uppercase' }] },
      pool,
      ctx
    )
    expect(output.output).toBe('HELLO WORLD')
    expect(output.length).toBe(11)
  })
})
