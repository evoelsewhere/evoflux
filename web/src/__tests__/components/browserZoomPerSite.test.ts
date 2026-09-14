/**
 * Zoom belongs to a site, not to the app.
 *
 * It used to be one preference applied everywhere: turning it up for a site
 * with small type turned it up for every other site, and for every session
 * after that.
 */

import { beforeEach, describe, expect, it } from 'vitest'

import {
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
