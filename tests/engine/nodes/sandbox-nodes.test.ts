import { describe, it, expect } from 'vitest'
import { NodeFactory } from '../../../src/engine/node-factory'
import { VariablePool } from '../../../src/engine/variable-pool'
import '../../../src/engine/nodes/index'

const pool = new VariablePool()
const ctx = { nodeId: 'sandbox-test', signal: undefined }

describe('CodeNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('code')
    expect(meta.type).toBe('code')
    expect(meta.category).toBe('tools')
    expect(meta.inputs.some(i => i.name === 'code')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'output')).toBe(true)
  })

  it('should execute JavaScript code', async () => {
    const node = NodeFactory.create('code')
    const output = await node.run(
      { language: 'javascript', code: 'console.log("hello")' },
      { language: 'javascript' },
      pool,
      ctx
    )
    expect(output.output).toContain('hello')
    expect(output.error).toBe('')
  })

  it('should return stderr on error', async () => {
    const node = NodeFactory.create('code')
    const output = await node.run(
      { language: 'javascript', code: 'throw new Error("test error")' },
      { language: 'javascript' },
      pool,
      ctx
    )
    expect(String(output.error)).toContain('test error')
  })

  it('should throw on missing code', async () => {
    const node = NodeFactory.create('code')
    await expect(
      node.run({}, { language: 'javascript' }, pool, ctx)
    ).rejects.toThrow('Code is required')
  })
})

describe('FileWriteNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('file-write')
    expect(meta.type).toBe('file-write')
    expect(meta.inputs.some(i => i.name === 'path')).toBe(true)
    expect(meta.inputs.some(i => i.name === 'content')).toBe(true)
  })

  it('should write a file', async () => {
    const node = NodeFactory.create('file-write')
    const output = await node.run(
      { path: 'output/test.txt', content: 'hello world' },
      {},
      pool,
      ctx
    )
    expect(output.path).toBe('output/test.txt')
    expect(output.bytes).toBe(11)
  })

  it('should throw on missing path', async () => {
    const node = NodeFactory.create('file-write')
    await expect(node.run({}, {}, pool, ctx)).rejects.toThrow('File path is required')
  })
})

describe('ShellNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('shell')
    expect(meta.type).toBe('shell')
    expect(meta.category).toBe('tools')
    expect(meta.outputs.some(o => o.name === 'stdout')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'exit_code')).toBe(true)
  })

  it('should execute a shell command', async () => {
    const node = NodeFactory.create('shell')
    const output = await node.run(
      { command: 'echo hello' },
      {},
      pool,
      ctx
    )
    expect(output.stdout).toContain('hello')
    expect(output.exit_code).toBe(0)
  })

  it('should handle non-zero exit code', async () => {
    const node = NodeFactory.create('shell')
    const output = await node.run(
      { command: 'exit 1' },
      {},
      pool,
      ctx
    )
    expect(output.exit_code).toBe(1)
  })

  it('should throw on missing command', async () => {
    const node = NodeFactory.create('shell')
    await expect(node.run({}, {}, pool, ctx)).rejects.toThrow('Command is required')
  })
})
