import { afterEach, describe, expect, it, mock } from 'bun:test'

let openerShouldReject = false
const openerCalls: string[] = []

mock.module('@tauri-apps/plugin-opener', () => ({
  openUrl: (url: string) => {
    openerCalls.push(url)
    if (openerShouldReject) return Promise.reject(new Error('not allowed'))
    return Promise.resolve(url)
  },
}))

const originalOpen = window.open

async function opener(): Promise<typeof import('@/lib/open-external')> {
  return import('@/lib/open-external')
}

function setTauriRuntime(enabled: boolean): void {
  const target = window as Window & { __TAURI_INTERNALS__?: unknown }
  if (enabled) {
    target.__TAURI_INTERNALS__ = {}
  } else {
    delete target.__TAURI_INTERNALS__
  }
}

afterEach(() => {
  window.open = originalOpen
  setTauriRuntime(false)
  openerShouldReject = false
  openerCalls.length = 0
})

describe('openExternalUrl', () => {
  it('uses window.open in the browser path', async () => {
    const calls: string[] = []
    window.open = ((url?: string | URL) => {
      calls.push(String(url))
      return null
    }) as typeof window.open

    const { openExternalUrl } = await opener()

    await openExternalUrl('https://auth.openai.com/codex/device')

    expect(calls).toEqual(['https://auth.openai.com/codex/device'])
    expect(openerCalls).toEqual([])
  })

  it('uses the Tauri opener when running inside the desktop shell', async () => {
    setTauriRuntime(true)
    window.open = mock(() => null) as typeof window.open
    const { openExternalUrl } = await opener()

    await openExternalUrl('https://github.com/login/device')

    expect(openerCalls).toEqual(['https://github.com/login/device'])
    expect(window.open).not.toHaveBeenCalled()
  })

  it('falls back to window.open if the Tauri opener rejects', async () => {
    setTauriRuntime(true)
    const calls: string[] = []
    window.open = ((url?: string | URL) => {
      calls.push(String(url))
      return null
    }) as typeof window.open
    openerShouldReject = true
    const { openExternalUrl } = await opener()

    await openExternalUrl('https://auth.openai.com/codex/device')

    expect(calls).toEqual(['https://auth.openai.com/codex/device'])
  })
})
