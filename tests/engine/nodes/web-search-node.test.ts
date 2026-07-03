import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import { NodeFactory } from '../../../src/engine/node-factory'
import { VariablePool } from '../../../src/engine/variable-pool'
import '../../../src/engine/nodes/index'
import { setupFetchMock, teardownFetchMock, createFetchResponse } from '../../helpers/mock-fetch'

const pool = new VariablePool()
const ctx = { nodeId: 'web-search-test', signal: undefined }

let fetchMock: ReturnType<typeof vi.fn>

beforeAll(() => {
  fetchMock = setupFetchMock()
})

afterAll(() => {
  teardownFetchMock()
})

describe('WebSearchNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('web-search')
    expect(meta.type).toBe('web-search')
    expect(meta.category).toBe('tools')
    expect(meta.inputs.some(i => i.name === 'query')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'results')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'formatted')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'count')).toBe(true)
  })

  it('should search and return results', async () => {
    const ddgHtml = `
      <html><body>
        <div class="result results--main">
          <div class="result__body">
            <a class="result__a" href="https://example.com/article1">Test Article 1</a>
            <a class="result__snippet">This is a test snippet about the topic.</a>
          </div>
          <div class="result__body">
            <a class="result__a" href="https://example.com/article2">Test Article 2</a>
            <a class="result__snippet">Another relevant result for testing.</a>
          </div>
        </div>
      </body></html>
    `
    fetchMock.mockResolvedValueOnce(createFetchResponse(ddgHtml))

    const node = NodeFactory.create('web-search')
    const output = await node.run(
      { query: 'test search' },
      { max_results: 5, language: 'en' },
      pool,
      ctx
    )

    expect(output.count).toBeGreaterThan(0)
    expect(Array.isArray(output.results)).toBe(true)
    expect(typeof output.formatted).toBe('string')
    expect(output.formatted).toContain('Found')
  })

  it('should throw on empty query', async () => {
    const node = NodeFactory.create('web-search')
    await expect(
      node.run({}, {}, pool, ctx)
    ).rejects.toThrow('Search query is required')
  })

  it('should handle fetch content mode', async () => {
    const ddgHtml = `
      <html><body>
        <div class="result__body">
          <a class="result__a" href="https://example.com/page1">Page Title</a>
          <a class="result__snippet">A snippet.</a>
        </div>
      </body></html>
    `
    fetchMock.mockResolvedValueOnce(createFetchResponse(ddgHtml))

    const pageHtml = '<html><head><title>Page Title</title></head><body><p>This is the main content of the page with enough text to be extracted properly.</p></body></html>'
    fetchMock.mockResolvedValueOnce(createFetchResponse(pageHtml))

    const node = NodeFactory.create('web-search')
    const output = await node.run(
      { query: 'test' },
      { max_results: 5, fetch_content: true, max_content_pages: 1 },
      pool,
      ctx
    )

    expect(output.count).toBeGreaterThan(0)
    const results = output.results as Array<{ content?: string }>
    expect(results[0].content).toBeDefined()
  })

  it('should handle network error gracefully', async () => {
    fetchMock.mockRejectedValueOnce(new Error('Network error'))

    const node = NodeFactory.create('web-search')
    await expect(
      node.run({ query: 'test' }, {}, pool, ctx)
    ).rejects.toThrow('Network error')
  })
})
