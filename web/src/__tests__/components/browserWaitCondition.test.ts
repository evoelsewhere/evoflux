import { describe, expect, it } from 'vitest'

import {
  browserViewportLayout,
  browserWaitConditionSatisfied,
} from '@/components/BrowserViewer/useDirectBrowserTabs'

const baseExpected = {
  selector: '#result',
  state: 'visible',
  text: 'Saved',
  urlContains: '/settings',
  loadState: 'complete',
}

describe('direct browser wait conditions', () => {
  it('requires every requested browser condition', () => {
    expect(browserWaitConditionSatisfied({
      attached: true,
      visible: true,
      text: 'Settings Saved',
      url: 'https://example.com/settings',
      readyState: 'complete',
    }, baseExpected)).toBe(true)

    expect(browserWaitConditionSatisfied({
      attached: true,
      visible: false,
      text: 'Settings Saved',
      url: 'https://example.com/settings',
      readyState: 'complete',
    }, baseExpected)).toBe(false)
  })

  it('treats a detached element as hidden', () => {
    expect(browserWaitConditionSatisfied({ attached: false }, {
      selector: '.toast',
      state: 'hidden',
      text: '',
      urlContains: '',
      loadState: '',
    })).toBe(true)
  })
})

describe('direct browser responsive viewport layout', () => {
  it('uses the browser panel bounds when no override is active', () => {
    expect(browserViewportLayout({ x: 12.4, y: 30.6, width: 719.7, height: 600.2 }, null))
      .toEqual({ x: 12, y: 31, width: 720, height: 600, scale: 1 })
  })

  it('scales and centers a desktop viewport without letting it cover app chrome', () => {
    expect(browserViewportLayout(
      { x: 300, y: 100, width: 640, height: 700 },
      { width: 1280, height: 800 },
    )).toEqual({
      x: 300,
      y: 250,
      width: 640,
      height: 400,
      scale: 0.5,
    })
  })

  it('keeps a mobile viewport at native CSS size and centers it', () => {
    expect(browserViewportLayout(
      { x: 100, y: 50, width: 700, height: 900 },
      { width: 375, height: 812 },
    )).toEqual({
      x: 263,
      y: 94,
      width: 375,
      height: 812,
      scale: 1,
    })
  })
})
