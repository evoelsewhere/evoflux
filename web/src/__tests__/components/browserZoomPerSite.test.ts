/**
 * Zoom belongs to a site, not to the app.
 *
 * It used to be one preference applied everywhere: turning it up for a site
 * with small type turned it up for every other site, and for every session
 * after that.
 */

import { beforeEach, describe, expect, it } from 'vitest'

import {
  browserConnectionInfo,
  browserZoomOrigin,
  loadBrowserZoomForOrigin,
  saveBrowserZoomForOrigin,
} from '@/components/BrowserViewer/browserPreferences'

describe('per-site browser zoom', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('keys zoom by scheme and host, ignoring path and query', () => {
    expect(browserZoomOrigin('https://example.com/docs?page=2')).toBe('https://example.com')
    expect(browserZoomOrigin('http://localhost:5173/x')).toBe('http://localhost:5173')
  })

  it('has no origin to remember for a page that is not on the web', () => {
    expect(browserZoomOrigin('about:blank')).toBeNull()
    expect(browserZoomOrigin('chrome-error://chromewebdata/')).toBeNull()
    expect(browserZoomOrigin('not a url')).toBeNull()
  })

  it('remembers a site and leaves its neighbours alone', () => {
    saveBrowserZoomForOrigin('https://example.com', 150)
    expect(loadBrowserZoomForOrigin('https://example.com')).toBe(150)
    expect(loadBrowserZoomForOrigin('https://other.example')).toBeNull()
  })

  it('forgets a site when it goes back to the default', () => {
    saveBrowserZoomForOrigin('https://example.com', 150)
    saveBrowserZoomForOrigin('https://example.com', null)
    expect(loadBrowserZoomForOrigin('https://example.com')).toBeNull()
  })

  it('ignores stored nonsense rather than applying it to a page', () => {
    localStorage.setItem(
      'oa.browser.zoom-by-origin',
      JSON.stringify({ 'https://example.com': 9000, 'https://two.example': 'big' }),
    )
    expect(loadBrowserZoomForOrigin('https://example.com')).toBeNull()
    expect(loadBrowserZoomForOrigin('https://two.example')).toBeNull()
  })
})

describe('browser connection info', () => {
  it('treats https as encrypted and says so', () => {
    const info = browserConnectionInfo('https://example.com/a')
    expect(info).toMatchObject({ encrypted: true, host: 'example.com', summary: 'Encrypted connection' })
  })

  it('does not call a local dev server insecure', () => {
    expect(browserConnectionInfo('http://localhost:5173/').summary)
      .toBe('Local server on this machine')
    expect(browserConnectionInfo('http://127.0.0.1:8080/').summary)
      .toBe('Local server on this machine')
  })

  it('warns for plain http on a real host', () => {
    const info = browserConnectionInfo('http://example.com/')
    expect(info.encrypted).toBe(false)
    expect(info.summary).toBe('Not encrypted')
  })

  it('has an answer for pages that are not on the web', () => {
    expect(browserConnectionInfo('file:///tmp/x.html').summary).toBe('File on this machine')
    expect(browserConnectionInfo('').summary).toBe('No page loaded')
  })
})
