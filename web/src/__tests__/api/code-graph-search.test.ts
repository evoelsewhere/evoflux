import { afterEach, describe, expect, it, vi } from 'vitest'
import { searchCodeGraph, searchProjectCodeGraph } from '@/api/client'

function searchResponse(): Response {
  return new Response(JSON.stringify({
    action: 'search',
    query: 'settle_pay',
    strategy: 'code-index-vector-fts5-cross-repo',
    index_version: 'version',
    repositories: [],
    stats: {},
    hits: [],
    matches: [],
    relations: [],
    suggestions: [],
    limitations: [],
    truncated: false,
  }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('code graph UI search', () => {
  it('reads the committed index and forwards cancellation for workspace and project searches', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => searchResponse())
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    await searchCodeGraph('/repo/app', 'settle_pay', {
      limit: 20,
      signal: controller.signal,
    })
    await searchProjectCodeGraph('project-1', 'settle_pay', {
      limit: 40,
      signal: controller.signal,
    })

    const workspaceRequest = fetchMock.mock.calls[0]?.[1] as RequestInit
    const projectRequest = fetchMock.mock.calls[1]?.[1] as RequestInit
    expect(JSON.parse(String(workspaceRequest.body))).toMatchObject({
      action: 'search',
      limit: 20,
      refresh: false,
    })
    expect(JSON.parse(String(projectRequest.body))).toMatchObject({
      action: 'search',
      limit: 40,
      refresh: false,
    })
    expect(workspaceRequest.signal).toBe(controller.signal)
    expect(projectRequest.signal).toBe(controller.signal)
  })
})
