import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import { NodeFactory } from '../../../src/engine/node-factory'
import { VariablePool } from '../../../src/engine/variable-pool'
import '../../../src/engine/nodes/index'
import { setupFetchMock, teardownFetchMock, createFetchResponse } from '../../helpers/mock-fetch'

const pool = new VariablePool()
const ctx = { nodeId: 'http-test', signal: undefined }

let fetchMock: ReturnType<typeof vi.fn>

beforeAll(() => {
  fetchMock = setupFetchMock()
})

afterAll(() => {
  teardownFetchMock()
})

describe('HTTPRequestNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('http-request')
    expect(meta.type).toBe('http-request')
    expect(meta.category).toBe('tools')
    expect(meta.inputs.some(i => i.name === 'url')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'status')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'response')).toBe(true)
  })

  it('should make GET request', async () => {
    fetchMock.mockResolvedValueOnce(createFetchResponse({ users: [1, 2, 3] }))
    const node = NodeFactory.create('http-request')
    const output = await node.run(
      { url: 'https://api.example.com/users' },
      { method: 'GET' },
      pool,
      ctx
    )
    expect(output.status).toBe(200)
    expect(output.response).toContain('users')
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.example.com/users',
      expect.objectContaining({ method: 'GET' })
    )
  })

  it('should make POST request with body', async () => {
    fetchMock.mockResolvedValueOnce(createFetchResponse({ id: 1 }, 201))
    const node = NodeFactory.create('http-request')
    const output = await node.run(
      { url: 'https://api.example.com/users', body: { name: 'John' } },
      { method: 'POST' },
      pool,
      ctx
    )
    expect(output.status).toBe(201)
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.example.com/users',
      expect.objectContaining({ method: 'POST', body: '{"name":"John"}' })
    )
  })

  it('should handle non-JSON response', async () => {
    fetchMock.mockResolvedValueOnce(createFetchResponse('<html>OK</html>'))
    const node = NodeFactory.create('http-request')
    const output = await node.run(
      { url: 'https://example.com' },
      { method: 'GET' },
      pool,
      ctx
    )
    expect(output.status).toBe(200)
    expect(output.response).toBe('<html>OK</html>')
  })

  it('should handle network error', async () => {
    fetchMock.mockRejectedValueOnce(new Error('ECONNREFUSED'))
    const node = NodeFactory.create('http-request')
    await expect(
      node.run({ url: 'https://unreachable.example.com' }, { method: 'GET' }, pool, ctx)
    ).rejects.toThrow('ECONNREFUSED')
  })

  it('should throw on missing URL', async () => {
    const node = NodeFactory.create('http-request')
    await expect(
      node.run({}, { method: 'GET' }, pool, ctx)
    ).rejects.toThrow('URL is required')
  })
})
