import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { NodeFactory } from '../../../src/engine/node-factory'
import { VariablePool } from '../../../src/engine/variable-pool'
import '../../../src/engine/nodes/index'
import { createCodeProject, type TestFixture } from '../../helpers/fixtures'

const pool = new VariablePool()
const ctx = { nodeId: 'fs-test', signal: undefined }

let fixture: TestFixture

beforeAll(async () => {
  fixture = await createCodeProject()
})

afterAll(async () => {
  await fixture.cleanup()
})

describe('FileExplorerNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('file-explorer')
    expect(meta.type).toBe('file-explorer')
    expect(meta.category).toBe('tools')
    expect(meta.inputs.some(i => i.name === 'root_path')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'files')).toBe(true)
  })

  it('should list files in directory', async () => {
    const node = NodeFactory.create('file-explorer')
    const output = await node.run(
      { root_path: fixture.dir },
      { exclude_patterns: ['node_modules', '.git'], max_depth: 3 },
      pool,
      ctx
    )
    expect(output.file_count).toBeGreaterThan(0)
    expect(Array.isArray(output.files)).toBe(true)
    const files = output.files as Array<{ name: string }>
    expect(files.some(f => f.name === 'index.ts')).toBe(true)
    expect(files.some(f => f.name === 'README.md')).toBe(true)
  })

  it('should filter by file types', async () => {
    const node = NodeFactory.create('file-explorer')
    const output = await node.run(
      { root_path: fixture.dir },
      { file_types: ['ts'], exclude_patterns: ['node_modules'] },
      pool,
      ctx
    )
    const files = output.files as Array<{ extension: string }>
    expect(files.every(f => f.extension === 'ts')).toBe(true)
  })

  it('should throw on missing root_path', async () => {
    const node = NodeFactory.create('file-explorer')
    await expect(node.run({}, {}, pool, ctx)).rejects.toThrow('Root path is required')
  })

  it('should respect max_files limit', async () => {
    const node = NodeFactory.create('file-explorer')
    const output = await node.run(
      { root_path: fixture.dir },
      { max_files: 2, exclude_patterns: ['node_modules', '.git'] },
      pool,
      ctx
    )
    expect((output.files as unknown[]).length).toBeLessThanOrEqual(2)
  })
})

describe('FileReaderNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('file-reader')
    expect(meta.type).toBe('file-reader')
    expect(meta.inputs.some(i => i.name === 'path')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'content')).toBe(true)
  })

  it('should read a text file', async () => {
    const node = NodeFactory.create('file-reader')
    const output = await node.run(
      { path: `${fixture.dir}/README.md` },
      { mode: 'plain' },
      pool,
      ctx
    )
    expect(output.content).toContain('Test Project')
    expect(output.metadata).toBeDefined()
    const meta = output.metadata as { extension: string; format: string }
    expect(meta.extension).toBe('md')
  })

  it('should throw on missing path', async () => {
    const node = NodeFactory.create('file-reader')
    await expect(node.run({}, {}, pool, ctx)).rejects.toThrow('File path is required')
  })

  it('should throw on non-existent file', async () => {
    const node = NodeFactory.create('file-reader')
    await expect(
      node.run({ path: '/nonexistent/file.txt' }, {}, pool, ctx)
    ).rejects.toThrow('File not found')
  })

  it('should reject files exceeding max_size_mb', async () => {
    const node = NodeFactory.create('file-reader')
    await expect(
      node.run({ path: `${fixture.dir}/README.md` }, { max_size_mb: 0.000001 }, pool, ctx)
    ).rejects.toThrow('File too large')
  })
})

describe('ContextLoaderNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('context-loader')
    expect(meta.type).toBe('context-loader')
    expect(meta.outputs.some(o => o.name === 'context')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'tree')).toBe(true)
  })

  it('should load project context', async () => {
    const node = NodeFactory.create('context-loader')
    const output = await node.run(
      { root_path: fixture.dir },
      { file_types: ['ts', 'md'], exclude_patterns: ['node_modules', '.git'], max_files: 10 },
      pool,
      ctx
    )
    expect(typeof output.context).toBe('string')
    expect(typeof output.tree).toBe('string')
    expect(output.files_loaded).toBeGreaterThan(0)
    expect(output.tree).toContain('index.ts')
  })

  it('should support tree_only mode', async () => {
    const node = NodeFactory.create('context-loader')
    const output = await node.run(
      { root_path: fixture.dir },
      { tree_only: true, exclude_patterns: ['node_modules', '.git'] },
      pool,
      ctx
    )
    expect(output.files_loaded).toBe(0)
    expect(typeof output.tree).toBe('string')
    expect(typeof output.context).toBe('string')
  })

  it('should throw on missing root_path', async () => {
    const node = NodeFactory.create('context-loader')
    await expect(node.run({}, {}, pool, ctx)).rejects.toThrow('Root path is required')
  })
})
