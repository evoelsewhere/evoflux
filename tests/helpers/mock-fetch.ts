import { vi } from 'vitest'

export interface MockFetchResponse {
  ok: boolean
  status: number
  text: () => Promise<string>
  json: () => Promise<unknown>
  headers: { forEach: (cb: (value: string, key: string) => void) => void }
}

export function createFetchResponse(body: unknown, status = 200): MockFetchResponse {
  const bodyStr = typeof body === 'string' ? body : JSON.stringify(body)
  const headerEntries: [string, string][] = [['content-type', typeof body === 'string' ? 'text/plain' : 'application/json']]
  return {
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(bodyStr),
    json: () => Promise.resolve(body),
    headers: {
      forEach: (cb: (value: string, key: string) => void) => {
        for (const [key, value] of headerEntries) cb(value, key)
      }
    },
  }
}

export function setupFetchMock(): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn().mockResolvedValue(createFetchResponse({ result: 'ok' }))
  Object.defineProperty(globalThis, 'fetch', {
    value: fetchMock,
    writable: true,
    configurable: true,
  })
  return fetchMock
}

export function teardownFetchMock(): void {
  // @ts-expect-error — cleanup test environment
  delete globalThis.fetch
}
