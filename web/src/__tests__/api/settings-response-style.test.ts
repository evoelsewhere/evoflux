import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  getResponseStyleSettings,
  updateResponseStyleSettings,
} from '@/api/client/settings'

function mockFetchResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => body,
  } as Response
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('response-style settings client', () => {
  it('GETs /settings/response-style without a request body', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(mockFetchResponse({ style: 'visual' }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await getResponseStyleSettings()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit | undefined]
    expect(url).toBe('/api/settings/response-style')
    expect(init?.method).toBeUndefined()
    expect(init?.body).toBeUndefined()
    expect(result).toEqual({ style: 'visual' })
  })

  it('PUTs the chosen style as JSON and maps the response', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(mockFetchResponse({ style: 'simple' }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await updateResponseStyleSettings({ style: 'simple' })

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/settings/response-style')
    expect(init.method).toBe('PUT')
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(init.body).toBe(JSON.stringify({ style: 'simple' }))
    expect(result).toEqual({ style: 'simple' })
  })

  it('surfaces the server detail when PUT is rejected', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(mockFetchResponse({ detail: 'Unknown style' }, false, 422))
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      updateResponseStyleSettings({ style: 'poetic' as 'simple' }),
    ).rejects.toThrow('Unknown style')
  })
})
