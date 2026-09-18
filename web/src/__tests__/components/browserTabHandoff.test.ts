/**
 * Handing a live page between surfaces. The rule worth testing is who is
 * allowed to pick one up: a WebView adopted by the wrong surface is a page
 * that disappears from one panel and turns up in another.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  claimBrowserTab,
  offerBrowserTab,
} from '@/components/BrowserViewer/browserTabHandoff'

const close = vi.fn()
const getByLabel = vi.fn(async (_label: string) => ({ close }))

vi.mock('@tauri-apps/api/webview', () => ({
  Webview: { getByLabel: (label: string) => getByLabel(label) },
}))

const offer = { label: 'browser-abc', url: 'https://example.com/page' }

beforeEach(() => {
  vi.useFakeTimers()
  close.mockClear()
  getByLabel.mockClear()
})

afterEach(() => {
  // Leave nothing pending: the offer is module state shared by every test.
  claimBrowserTab('s1', 'panel-1')
  vi.useRealTimers()
})

describe('browser tab handoff', () => {
  it('gives the page to the surface it was offered to', () => {
    offerBrowserTab('s1', 'panel-1', offer)
    expect(claimBrowserTab('s1', 'panel-1')).toEqual(offer)
  })

  it('is collected exactly once', () => {
    offerBrowserTab('s1', 'panel-1', offer)
    expect(claimBrowserTab('s1', 'panel-1')).toEqual(offer)
    expect(claimBrowserTab('s1', 'panel-1')).toBeNull()
  })

  it('refuses another panel, and another session', () => {
    offerBrowserTab('s1', 'panel-1', offer)
    expect(claimBrowserTab('s1', 'panel-2')).toBeNull()
    expect(claimBrowserTab('s2', 'panel-1')).toBeNull()
    // Still there for the one it was meant for.
    expect(claimBrowserTab('s1', 'panel-1')).toEqual(offer)
  })

  it('closes a page nobody came for, rather than stranding it on screen', async () => {
    offerBrowserTab('s1', 'panel-1', offer)
    await vi.advanceTimersByTimeAsync(30_000)
    await vi.waitFor(() => expect(close).toHaveBeenCalledTimes(1))
    expect(getByLabel).toHaveBeenCalledWith('browser-abc')
    expect(claimBrowserTab('s1', 'panel-1')).toBeNull()
  })

  it('does not close a page that was collected in time', async () => {
    offerBrowserTab('s1', 'panel-1', offer)
    expect(claimBrowserTab('s1', 'panel-1')).toEqual(offer)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(close).not.toHaveBeenCalled()
  })

  it('does not leave the page of a superseded offer behind', async () => {
    offerBrowserTab('s1', 'panel-1', offer)
    offerBrowserTab('s1', 'panel-2', { label: 'browser-def', url: 'https://example.org' })
    await vi.waitFor(() => expect(getByLabel).toHaveBeenCalledWith('browser-abc'))
    expect(claimBrowserTab('s1', 'panel-2')?.label).toBe('browser-def')
  })
})
